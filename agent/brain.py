# agent/brain.py — Cerebro del agente: conexion con Claude
# Generado por AgentKit

"""
Logica de IA del agente. Lee el system prompt de config/prompts.yaml y genera las
respuestas con la API de Anthropic.
"""

import logging
import os

import yaml
from anthropic import AsyncAnthropic
from dotenv import load_dotenv

from agent.tools import ESQUEMAS_HERRAMIENTAS, ejecutar_herramienta, obtener_horario

load_dotenv()
logger = logging.getLogger("agentkit")

client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# El modelo se cambia desde .env, sin tocar el codigo.
#   claude-opus-5     el mas capaz             $5 / $25 por millon de tokens
#   claude-sonnet-5   el balanceado (default)  $3 / $15
#   claude-haiku-4-5  el mas barato y rapido   $1 / $5
# El "or" y no el default de os.getenv: una variable declarada vacia en el .env
# devuelve "" y dejaria al agente sin modelo.
MODELO = os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-5"

# Es un bot de respuestas cortas: con esfuerzo bajo contesta mas rapido y mas barato.
# Dejalo vacio en el .env para no mandar el parametro.
ESFUERZO = os.getenv("ANTHROPIC_EFFORT", "low").strip()

# WhatsApp son mensajes cortos, pero este tope NO es solo la respuesta: en los modelos
# actuales el razonamiento interno tambien cuenta contra el. Con el margen justo, una
# pregunta que exija pensar un poco deja al agente sin espacio para contestar.
MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS") or "4096")

# Los modelos mas viejos no aceptan output_config. Si la primera llamada falla por eso,
# se reintenta sin el parametro y se recuerda para las siguientes.
_soporta_esfuerzo = True

# Cuantas veces puede el agente pedir herramientas antes de tener que contestar. Una
# conversacion normal usa 1 (registrar el pedido); el tope es para que un modelo que se
# atore pidiendo lo mismo no se quede dando vueltas ni queme tokens.
MAX_VUELTAS_HERRAMIENTAS = 5


def cargar_config_prompts() -> dict:
    """Lee toda la configuracion desde config/prompts.yaml."""
    try:
        with open("config/prompts.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.error("config/prompts.yaml no encontrado")
        return {}


def cargar_system_prompt() -> str:
    """El system prompt: quien es el agente y que sabe del negocio."""
    return cargar_config_prompts().get(
        "system_prompt", "Eres un asistente util. Responde siempre en espanol."
    )


def obtener_mensaje_error() -> str:
    """Que decirle al cliente cuando algo falla de nuestro lado."""
    return cargar_config_prompts().get(
        "error_message",
        "Lo siento, estoy teniendo problemas tecnicos. Por favor intenta de nuevo en unos minutos.",
    )


def obtener_mensaje_fallback() -> str:
    """Que decirle al cliente cuando no se entendio el mensaje."""
    return cargar_config_prompts().get(
        "fallback_message", "Disculpa, no entendi tu mensaje. Podrias reformularlo?"
    )


def _extraer_texto(respuesta) -> str:
    """
    Junta el texto de la respuesta de Claude.

    Ojo: NO se puede hacer respuesta.content[0].text. La respuesta es una lista de
    bloques y el primero no siempre es texto (los modelos que razonan devuelven
    primero un bloque de pensamiento). Hay que filtrar por tipo.
    """
    partes = [bloque.text for bloque in respuesta.content if bloque.type == "text"]
    return "\n".join(p for p in partes if p).strip()


def _contexto_del_momento() -> str:
    """
    Lo que el modelo no puede saber por si mismo: en que momento esta ocurriendo la
    conversacion y si el negocio esta abierto.

    Sin esto, la regla de "fuera de horario" del system prompt es letra muerta: el
    modelo no tiene reloj y no puede decidir si aplicarla.
    """
    h = obtener_horario()
    estado = "ABIERTO" if h["esta_abierto"] else "CERRADO"
    return (
        "\n\n## Momento actual\n"
        f"Ahora mismo es {h['hora_local']} (hora del negocio) y el negocio esta {estado}. "
        f"Horario: {h['horario']}.\n"
        "Si esta CERRADO, avisale al cliente del horario, pero igual atiendelo y toma su "
        "pedido: no lo dejes esperando hasta el dia siguiente."
    )


def _es_error_de_esfuerzo(error: Exception) -> bool:
    """
    True solo si el modelo rechazo la llamada POR el parametro output_config/effort.

    Se exige que sea un 400 de peticion invalida y no cualquier error que mencione la
    palabra: un 529 de sobrecarga que la nombre de paso no debe apagar el parametro
    para todo el proceso.
    """
    if getattr(error, "status_code", None) != 400:
        return False
    texto = str(error).lower()
    return "output_config" in texto or "effort" in texto


async def generar_respuesta(
    mensaje: str, historial: list[dict], telefono: str = ""
) -> tuple[str, bool]:
    """
    Genera una respuesta con Claude, dejandolo usar herramientas si hacen falta.

    Args:
        mensaje: el mensaje nuevo del cliente
        historial: los mensajes anteriores, [{"role": "user"|"assistant", "content": "..."}]
        telefono: el numero de esta conversacion. Se le pasa al despachador de
            herramientas para que un pedido quede guardado a nombre de quien escribe;
            el modelo nunca elige a que telefono escribir.

    Returns:
        (texto, es_respuesta_real)

        "es_respuesta_real" es False cuando lo que se devuelve es un aviso tecnico
        (error o fallback) y no una respuesta del agente. main.py lo usa para no
        guardar esos avisos en el historial: si se guardaran, quedarian contaminando
        el contexto de todos los mensajes siguientes.
    """
    global _soporta_esfuerzo

    if not mensaje or len(mensaje.strip()) < 2:
        return obtener_mensaje_fallback(), False

    mensajes = [{"role": m["role"], "content": m["content"]} for m in historial]
    mensajes.append({"role": "user", "content": mensaje})

    system_prompt = cargar_system_prompt() + _contexto_del_momento()

    async def _llamar(parametros_extra: dict):
        return await client.messages.create(
            model=MODELO,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=mensajes,
            tools=ESQUEMAS_HERRAMIENTAS,
            **parametros_extra,
        )

    async def _llamar_con_reintento():
        """Una llamada al modelo, apagando output_config si este modelo no lo acepta."""
        global _soporta_esfuerzo
        parametros = {"output_config": {"effort": ESFUERZO}} if (_soporta_esfuerzo and ESFUERZO) else {}
        try:
            return await _llamar(parametros)
        except Exception as e:  # noqa: BLE001
            if parametros and _es_error_de_esfuerzo(e):
                logger.warning(
                    f"El modelo {MODELO} no acepta output_config.effort; se reintenta sin ese parametro."
                )
                _soporta_esfuerzo = False
                return await _llamar({})
            raise

    respuesta = None
    for vuelta in range(MAX_VUELTAS_HERRAMIENTAS + 1):
        try:
            respuesta = await _llamar_con_reintento()
        except Exception as e:  # noqa: BLE001
            logger.error(f"Error llamando a Claude: {e}")
            return obtener_mensaje_error(), False

        if getattr(respuesta, "stop_reason", None) == "max_tokens":
            logger.warning(
                f"La respuesta se corto por llegar al tope de {MAX_TOKENS} tokens. "
                "Si pasa seguido, sube ANTHROPIC_MAX_TOKENS o acorta el system prompt."
            )

        if respuesta.stop_reason != "tool_use":
            break

        if vuelta == MAX_VUELTAS_HERRAMIENTAS:
            logger.error(
                f"El agente pidio herramientas {MAX_VUELTAS_HERRAMIENTAS} veces seguidas sin "
                "contestar; se corta el ciclo."
            )
            return obtener_mensaje_error(), False

        # Se devuelve el turno completo del asistente (incluidos los bloques de tool_use)
        # y despues los resultados. La API exige que cada tool_use tenga su tool_result
        # con el mismo id, en el turno inmediatamente siguiente.
        mensajes.append({"role": "assistant", "content": respuesta.content})

        resultados = []
        for bloque in respuesta.content:
            if bloque.type != "tool_use":
                continue
            logger.info(f"El agente usa la herramienta {bloque.name} para {telefono}")
            salida = await ejecutar_herramienta(bloque.name, bloque.input or {}, telefono)
            resultados.append(
                {
                    "type": "tool_result",
                    "tool_use_id": bloque.id,
                    "content": salida,
                    "is_error": salida.startswith("ERROR"),
                }
            )
        mensajes.append({"role": "user", "content": resultados})

    texto = _extraer_texto(respuesta)
    if not texto:
        logger.warning("Claude devolvio una respuesta sin texto")
        return obtener_mensaje_fallback(), False

    logger.info(
        f"Respuesta generada con {MODELO} "
        f"({respuesta.usage.input_tokens} in / {respuesta.usage.output_tokens} out)"
    )
    return texto, True
