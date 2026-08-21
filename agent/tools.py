# agent/tools.py — Herramientas del agente
# Generado por AgentKit

"""
Herramientas especificas del negocio (LA TAQUERA).

La informacion del negocio (precios, productos, como comprar) le llega al agente por el
system prompt (config/prompts.yaml), asi que para CONTESTAR preguntas no hace falta nada
de aca. Este archivo tiene las ACCIONES: registrar un pedido, guardar un lead, abrir un
ticket, buscar en /knowledge.

Esas acciones SI las ejecuta el agente por su cuenta: al final del archivo estan los
esquemas que se le pasan a Claude (ESQUEMAS_HERRAMIENTAS) y el despachador que las corre
(ejecutar_herramienta). El ciclo de tool use vive en agent/brain.py.

El telefono nunca lo elige el modelo: lo pone el despachador con el numero de la
conversacion en curso, para que no pueda escribir un pedido a nombre de otro cliente.

Casos de uso de LA TAQUERA: FAQ, tomar pedidos, ventas / atender interesados, soporte
post-venta.
"""

import logging
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from agent.memory import Base, async_session, engine

logger = logging.getLogger("agentkit")

CARPETA_KNOWLEDGE = Path("knowledge")


def cargar_info_negocio() -> dict:
    """Carga la informacion del negocio desde config/business.yaml."""
    try:
        with open("config/business.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.error("config/business.yaml no encontrado")
        return {}


def zona_del_negocio() -> tzinfo:
    """
    Zona horaria del negocio. Se lee de business.yaml y, si el sistema no trae la
    base de datos de zonas (pasa en Windows sin el paquete `tzdata`), cae a un
    UTC-6 fijo, que es la hora del centro de Mexico salvo cambios de horario.
    """
    nombre = (
        cargar_info_negocio().get("negocio", {}).get("horario_estructurado", {}).get("zona")
        or "America/Mexico_City"
    )
    try:
        return ZoneInfo(nombre)
    except Exception:  # noqa: BLE001  (ZoneInfoNotFoundError y afines)
        logger.warning(f"No se encontro la zona horaria '{nombre}'; se usa UTC-6 fijo.")
        return timezone(timedelta(hours=-6))


def obtener_horario() -> dict:
    """
    Estado real del horario de atencion: que dice el horario, si esta abierto ahora
    mismo y la hora local del negocio.

    Antes esto devolvia siempre esta_abierto=True, asi que la regla de "fuera de
    horario" del system prompt no podia cumplirse nunca.
    """
    negocio = cargar_info_negocio().get("negocio", {})
    est = negocio.get("horario_estructurado", {}) or {}

    dias = est.get("dias", [0, 1, 2, 3, 4])          # 0 = lunes ... 6 = domingo
    inicio = str(est.get("inicio", "09:00"))
    fin = str(est.get("fin", "18:00"))

    ahora_local = datetime.now(zona_del_negocio())

    def _a_minutos(hhmm: str, por_defecto: int) -> int:
        try:
            h, m = hhmm.split(":")
            return int(h) * 60 + int(m)
        except (ValueError, AttributeError):
            return por_defecto

    minuto_actual = ahora_local.hour * 60 + ahora_local.minute
    abierto = (
        ahora_local.weekday() in dias
        and _a_minutos(inicio, 540) <= minuto_actual < _a_minutos(fin, 1080)
    )

    return {
        "horario": negocio.get("horario", "No disponible"),
        "esta_abierto": abierto,
        "hora_local": ahora_local.strftime("%A %d/%m/%Y %H:%M"),
    }


def buscar_en_knowledge(consulta: str) -> str:
    """
    Busca informacion en los archivos de /knowledge.
    Retorna los fragmentos que coinciden con la consulta.
    """
    if not CARPETA_KNOWLEDGE.is_dir():
        return "No hay archivos de conocimiento disponibles."

    resultados = []
    for ruta in sorted(CARPETA_KNOWLEDGE.iterdir()):
        if ruta.name.startswith(".") or not ruta.is_file():
            continue
        try:
            contenido = ruta.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binarios y archivos ilegibles se saltean
        if consulta.lower() in contenido.lower():
            resultados.append(f"[{ruta.name}]: {contenido[:500]}")

    if resultados:
        return "\n---\n".join(resultados)
    return "No encontre informacion especifica sobre eso en mis archivos."


def ahora() -> datetime:
    return datetime.now(timezone.utc)


# ════════════════════════════════════════════════════════════
# TOMAR PEDIDOS
# ════════════════════════════════════════════════════════════


class Pedido(Base):
    """Un pedido tomado por WhatsApp. Estado inicial siempre 'nuevo' — lo confirma
    y cobra un humano del negocio; el agente no procesa pagos."""

    __tablename__ = "pedidos_whatsapp"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefono: Mapped[str] = mapped_column(String(50), index=True)
    resumen: Mapped[str] = mapped_column(Text)  # texto libre: productos, cantidades, envio
    estado: Mapped[str] = mapped_column(String(30), default="nuevo")
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)


async def registrar_pedido(telefono: str, resumen: str) -> int:
    """
    Guarda un pedido tomado por WhatsApp en estado 'nuevo'.

    No cobra ni descuenta inventario — eso lo hace un humano del negocio (o el flujo de
    Mercado Pago en la pagina) despues de revisar el pedido con el cliente.
    """
    async with async_session() as session:
        pedido = Pedido(telefono=telefono, resumen=resumen, estado="nuevo", creado_en=ahora())
        session.add(pedido)
        await session.commit()
        await session.refresh(pedido)
        logger.info(f"Pedido #{pedido.id} registrado para {telefono}")
        return pedido.id


# ════════════════════════════════════════════════════════════
# VENTAS / LEADS
# ════════════════════════════════════════════════════════════


class Lead(Base):
    """Alguien que mostro interes pero todavia no compra."""

    __tablename__ = "leads_whatsapp"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefono: Mapped[str] = mapped_column(String(50), index=True)
    nombre: Mapped[str] = mapped_column(String(120), default="")
    interes: Mapped[str] = mapped_column(Text, default="")
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)


async def registrar_lead(telefono: str, nombre: str, interes: str) -> int:
    """Guarda un lead — alguien interesado que todavia no compro."""
    async with async_session() as session:
        lead = Lead(telefono=telefono, nombre=nombre, interes=interes, creado_en=ahora())
        session.add(lead)
        await session.commit()
        await session.refresh(lead)
        logger.info(f"Lead #{lead.id} registrado para {telefono}")
        return lead.id


# ════════════════════════════════════════════════════════════
# SOPORTE POST-VENTA
# ════════════════════════════════════════════════════════════


class Ticket(Base):
    """Un reporte de soporte post-venta (duda o problema con un pedido ya hecho)."""

    __tablename__ = "tickets_whatsapp"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefono: Mapped[str] = mapped_column(String(50), index=True)
    problema: Mapped[str] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(30), default="abierto")
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)


async def crear_ticket(telefono: str, problema: str) -> int:
    """Abre un ticket de soporte para que un humano del negocio le de seguimiento."""
    async with async_session() as session:
        ticket = Ticket(telefono=telefono, problema=problema, estado="abierto", creado_en=ahora())
        session.add(ticket)
        await session.commit()
        await session.refresh(ticket)
        logger.info(f"Ticket #{ticket.id} abierto para {telefono}")
        return ticket.id


async def crear_tablas_tools():
    """Crea las tablas de pedidos/leads/tickets si no existen. Llamar junto a inicializar_db()."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ════════════════════════════════════════════════════════════
# CONEXION CON CLAUDE (tool use)
# ════════════════════════════════════════════════════════════

# Lo que el agente puede HACER, no solo decir. Estos esquemas se le pasan a Claude en
# cada llamada; cuando decide usar uno, brain.py llama a ejecutar_herramienta().
ESQUEMAS_HERRAMIENTAS = [
    {
        "name": "registrar_pedido",
        "description": (
            "Guarda un pedido que el cliente ya confirmo por WhatsApp. Usala SOLO despues de "
            "que el cliente haya confirmado productos, cantidades y —si es envio— la direccion "
            "completa. No cobra nada: dejar el pedido registrado es lo que permite que alguien "
            "del negocio lo revise y le cobre. Si no la usas, el pedido se pierde."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "resumen": {
                    "type": "string",
                    "description": (
                        "El pedido completo en texto: productos con cantidades, total en MXN, "
                        "nombre del cliente y datos de envio si aplica (calle, colonia, ciudad, "
                        "estado, codigo postal)."
                    ),
                }
            },
            "required": ["resumen"],
        },
    },
    {
        "name": "registrar_lead",
        "description": (
            "Guarda a alguien que mostro interes pero todavia no cierra la compra: pregunto "
            "precios, dijo que lo iba a pensar, pidio fotos. Sirve para que el negocio le pueda "
            "dar seguimiento despues."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre": {"type": "string", "description": "Nombre del cliente, o cadena vacia si no lo dijo."},
                "interes": {"type": "string", "description": "Que le interesa y en que quedo la conversacion."},
            },
            "required": ["interes"],
        },
    },
    {
        "name": "crear_ticket",
        "description": (
            "Abre un reporte para que un humano del negocio de seguimiento: problemas con un "
            "pedido ya hecho, retrasos, reembolsos, fallas de pago, o cualquier cosa que no "
            "puedas resolver tu."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "problema": {"type": "string", "description": "Que reporta el cliente, con el detalle que haya dado."},
            },
            "required": ["problema"],
        },
    },
    {
        "name": "buscar_en_knowledge",
        "description": (
            "Busca en los archivos de conocimiento del negocio (productos, precios, envios). "
            "Usala cuando te pregunten un detalle que no tengas a la mano en tus instrucciones, "
            "antes de decir que no sabes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "consulta": {"type": "string", "description": "Palabra o frase a buscar."},
            },
            "required": ["consulta"],
        },
    },
]


async def ejecutar_herramienta(nombre: str, argumentos: dict, telefono: str) -> str:
    """
    Corre la herramienta que pidio el modelo y devuelve el resultado como texto.

    El telefono lo pone el llamador (la conversacion en curso), nunca el modelo.
    Nunca lanza: si algo falla, devuelve el error como texto para que el agente pueda
    decirle algo util al cliente en vez de quedarse callado.
    """
    try:
        if nombre == "registrar_pedido":
            resumen = str(argumentos.get("resumen", "")).strip()
            if not resumen:
                return "ERROR: el resumen del pedido venia vacio; no se guardo nada."
            pedido_id = await registrar_pedido(telefono, resumen)
            return f"Pedido #{pedido_id} registrado. El negocio ya lo puede ver y darle seguimiento."

        if nombre == "registrar_lead":
            lead_id = await registrar_lead(
                telefono,
                str(argumentos.get("nombre", "") or "").strip(),
                str(argumentos.get("interes", "") or "").strip(),
            )
            return f"Lead #{lead_id} registrado."

        if nombre == "crear_ticket":
            problema = str(argumentos.get("problema", "")).strip()
            if not problema:
                return "ERROR: el reporte venia vacio; no se abrio ningun ticket."
            ticket_id = await crear_ticket(telefono, problema)
            return f"Ticket #{ticket_id} abierto. Alguien del equipo le va a dar seguimiento."

        if nombre == "buscar_en_knowledge":
            return buscar_en_knowledge(str(argumentos.get("consulta", "")))

        logger.warning(f"El modelo pidio una herramienta desconocida: {nombre}")
        return f"ERROR: no existe la herramienta '{nombre}'."

    except Exception as e:  # noqa: BLE001
        logger.exception(f"Fallo la herramienta {nombre}: {e}")
        return f"ERROR ejecutando {nombre}: {e}"
