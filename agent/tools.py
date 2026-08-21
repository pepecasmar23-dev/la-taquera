# agent/tools.py — Herramientas del agente
# Generado por AgentKit

"""
Herramientas especificas del negocio (LA TAQUERA).

OJO: estas funciones NO se ejecutan solas todavia. La informacion del negocio (precios,
productos, como comprar) le llega al agente por el system prompt (config/prompts.yaml),
asi que para CONTESTAR preguntas no hace falta nada de aca. Este archivo es el lugar
para las ACCIONES —registrar un pedido, guardar un lead, abrir un ticket— y conectarlas
al ciclo de tool use de Claude (para que el agente las ejecute solo, no solo hable de
ellas) es un paso aparte, todavia no incluido en agent/brain.py.

Casos de uso de LA TAQUERA: FAQ, tomar pedidos, ventas / atender interesados, soporte
post-venta.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

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


def obtener_horario() -> dict:
    """Retorna el horario de atencion del negocio."""
    info = cargar_info_negocio()
    return {
        "horario": info.get("negocio", {}).get("horario", "No disponible"),
        "esta_abierto": True,  # TODO: calcular segun la hora actual y el horario
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
