# Don Ajo — agente de WhatsApp de LA TAQUERA

Servidor del agente de WhatsApp con IA (Claude) para LA TAQUERA. Construido con
[AgentKit](https://github.com/hainrixz/whatsapp-agentkit).

Responde preguntas frecuentes, toma pedidos, atiende a interesados y da soporte
post-venta, hablando con la personalidad de la marca.

## Variables de entorno que hay que configurar en Railway (Variables tab)

- `ANTHROPIC_API_KEY` — tu API key de Anthropic (platform.anthropic.com).
- `ZERNIO_API_KEY` — API key de tu cuenta de Zernio.
- `ZERNIO_WEBHOOK_SECRET` — un secreto que tú inventas, se usa para verificar que los
  webhooks vienen de verdad de Zernio.
- `ZERNIO_ACCOUNT_ID` — opcional, solo para el chequeo de conexión al arrancar.
- `ENVIRONMENT=production`
- `WHATSAPP_PROVIDER=zernio` (ya viene en el código, no hace falta repetirlo salvo que
  quieras sobreescribirlo)

`.env` nunca se sube a git — esas variables se configuran directo en Railway.

## Estructura

```
agent/            servidor (FastAPI), cerebro (Claude), memoria, herramientas
config/           business.yaml y prompts.yaml — datos y personalidad del agente
knowledge/        info de precios/productos que el agente puede consultar
tests/test_local.py   chat de prueba en terminal, sin necesitar WhatsApp
tests/test_herramientas.py  comprueba que el agente ejecuta sus herramientas
```

## Probar sin WhatsApp

```bash
pip install -r requirements.txt
cp .env.example .env   # y completa ANTHROPIC_API_KEY
python tests/test_local.py
```

## Comprobar que las herramientas funcionan

Esta prueba no necesita clave de API ni WhatsApp: sustituye al modelo por uno falso
y verifica que un pedido confirmado llega de verdad a la base de datos.

```bash
python tests/test_herramientas.py
```
