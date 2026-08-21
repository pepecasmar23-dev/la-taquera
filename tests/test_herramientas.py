# tests/test_herramientas.py — Prueba del ciclo de tool use
#
# Comprueba que el agente EJECUTA las herramientas y no solo habla de ellas.
# No necesita clave de API ni WhatsApp: sustituye al cliente de Anthropic por uno
# falso con respuestas preparadas, y usa una base SQLite temporal.
#
# Se ejecuta con:
#     python tests/test_herramientas.py

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Base temporal y clave falsa: hay que dejarlas puestas ANTES de importar agent.*,
# porque memory.py lee DATABASE_URL al importarse.
_BASE_TMP = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_BASE_TMP}"
os.environ.setdefault("ANTHROPIC_API_KEY", "clave-falsa-para-pruebas")

from agent import brain  # noqa: E402
from agent.memory import inicializar_db  # noqa: E402
from agent.tools import crear_tablas_tools  # noqa: E402

TELEFONO = "521844TEST"

fallos = 0


def check(nombre, condicion, extra=""):
    global fallos
    print(("  ok    " if condicion else "  FALLA ") + nombre + (f"  -> {extra}" if extra else ""))
    if not condicion:
        fallos += 1


# ── Dobles de prueba: imitan la forma de la respuesta del SDK ────────────────


class BloqueTexto:
    type = "text"

    def __init__(self, texto):
        self.text = texto


class BloqueHerramienta:
    type = "tool_use"

    def __init__(self, id_, nombre, entrada):
        self.id = id_
        self.name = nombre
        self.input = entrada


class Uso:
    input_tokens = 100
    output_tokens = 50


class Respuesta:
    def __init__(self, contenido, stop_reason):
        self.content = contenido
        self.stop_reason = stop_reason
        self.usage = Uso()


class ClienteFalso:
    """Devuelve las respuestas preparadas, una por llamada, y guarda lo que recibio."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = []
        self.messages = self

    async def create(self, **kwargs):
        self.llamadas.append(kwargs)
        return self.respuestas.pop(0)


async def main():
    await inicializar_db()
    await crear_tablas_tools()
    original = brain.client

    # ── 1. El caso que importa: el cliente confirma y el pedido queda guardado ──
    cliente = ClienteFalso([
        Respuesta(
            [
                BloqueTexto("Va, lo registro."),
                BloqueHerramienta("tu_1", "registrar_pedido", {"resumen": "2 gorras negras, $858 MXN, Juan Perez"}),
            ],
            "tool_use",
        ),
        Respuesta([BloqueTexto("Listo Juan, tu pedido quedo registrado. Te escribimos para el pago.")], "end_turn"),
    ])
    brain.client = cliente

    texto, real = await brain.generar_respuesta("Si, confirmo las dos gorras negras", [], TELEFONO)

    check("la respuesta final llega al cliente", real and "registrado" in texto.lower(), texto[:60])
    check("se llamo dos veces al modelo (herramienta + respuesta)", len(cliente.llamadas) == 2, f"{len(cliente.llamadas)} llamadas")
    check("las herramientas se le pasan al modelo", "tools" in cliente.llamadas[0], list(cliente.llamadas[0].keys()))

    # La segunda llamada debe llevar el turno del asistente y el resultado de la herramienta
    mensajes_segunda = cliente.llamadas[1]["messages"]
    resultado = mensajes_segunda[-1]["content"][0]
    check("el resultado vuelve al modelo con su tool_use_id", resultado["tool_use_id"] == "tu_1")
    check("el resultado no viene marcado como error", resultado["is_error"] is False, resultado["content"][:50])
    check("el pedido quedo confirmado en el resultado", "Pedido #" in resultado["content"], resultado["content"][:50])

    # ── 2. Y de verdad esta en la base de datos ────────────────────────────────
    from sqlalchemy import select

    from agent.memory import async_session
    from agent.tools import Pedido

    async with async_session() as s:
        pedidos = (await s.execute(select(Pedido))).scalars().all()
    check("el pedido esta guardado en la base", len(pedidos) == 1, f"{len(pedidos)} pedidos")
    if pedidos:
        check("guardado con el telefono de la conversacion", pedidos[0].telefono == TELEFONO, pedidos[0].telefono)
        check("guardado en estado 'nuevo'", pedidos[0].estado == "nuevo")
        check("con el resumen del pedido", "gorras" in pedidos[0].resumen)

    # ── 3. La hora: el modelo recibe el momento actual ─────────────────────────
    system = cliente.llamadas[0]["system"]
    check("el system prompt incluye el momento actual", "## Momento actual" in system)
    check("dice si esta abierto o cerrado", ("ABIERTO" in system) or ("CERRADO" in system))

    # ── 4. Un modelo atorado no da vueltas para siempre ────────────────────────
    en_bucle = ClienteFalso([
        Respuesta([BloqueHerramienta(f"tu_{i}", "buscar_en_knowledge", {"consulta": "salsa"})], "tool_use")
        for i in range(brain.MAX_VUELTAS_HERRAMIENTAS + 1)
    ])
    brain.client = en_bucle
    texto_bucle, real_bucle = await brain.generar_respuesta("hola que tal", [], TELEFONO)
    check("corta el ciclo si el modelo se atora", real_bucle is False)
    check("no se pasa del tope de vueltas", len(en_bucle.llamadas) == brain.MAX_VUELTAS_HERRAMIENTAS + 1,
          f"{len(en_bucle.llamadas)} llamadas")

    # ── 5. Una herramienta que falla no tumba la conversacion ──────────────────
    con_error = ClienteFalso([
        Respuesta([BloqueHerramienta("tu_x", "herramienta_inventada", {})], "tool_use"),
        Respuesta([BloqueTexto("Disculpa, deja te ayudo de otra forma.")], "end_turn"),
    ])
    brain.client = con_error
    texto_err, real_err = await brain.generar_respuesta("quiero algo raro", [], TELEFONO)
    check("una herramienta inexistente no rompe la respuesta", real_err is True, texto_err[:40])
    check("el error se le informa al modelo",
          con_error.llamadas[1]["messages"][-1]["content"][0]["is_error"] is True)

    brain.client = original
    print("\nTodo bien." if fallos == 0 else f"\n{fallos} fallo(s).")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
