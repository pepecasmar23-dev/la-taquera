# LA TAQUERA — servidor de pagos (Mercado Pago)

Servidor Node.js/Express que le agrega checkout real a la landing de LA TAQUERA:
botón de compra → Checkout Pro de Mercado Pago (tarjeta, OXXO, transferencia/SPEI) →
webhook que confirma el pago → aviso de "ya pagaste" → endpoint de reembolso.

Construido siguiendo el mismo set de reglas de seguridad que usa el subagente
`integration-specialist` de PagoKit (ver `SECURITY_RULES.md` del plugin `payment-advisor`):
sin llaves hardcodeadas, `.env` en `.gitignore` desde el inicio, verificación de firma
del webhook con el body crudo, llaves de idempotencia con `crypto.randomUUID()`,
deduplicación de eventos repetidos, y cero manejo de datos de tarjeta (todo pasa por
la página alojada de Mercado Pago, nunca toca nuestro servidor).

## 1. Instalar

```bash
cd server
npm install
```

## 2. Configurar credenciales

```bash
cp .env.example .env
```

Edita `.env` y completa:

- `MP_ACCESS_TOKEN` — tu Access Token de Mercado Pago (panel: *Tu negocio → Configuración →
  Credenciales*). Empieza con `TEST-` (pruebas) o `APP_USR-` (real).
- `MP_WEBHOOK_SECRET` — la clave secreta que Mercado Pago te da al configurar la URL de
  notificaciones webhook (mismo panel, sección *Notificaciones webhook*).
- `ADMIN_KEY` — invéntate una clave larga y aleatoria; protege el endpoint de reembolsos.
- `PUBLIC_BASE_URL` — la URL pública donde corre este servidor (ver punto 4, webhooks).

`.env` nunca se sube a git (ya está en `.gitignore`) y nunca aparece en el HTML que ve
el cliente — solo vive en el servidor.

## 3. Correr

```bash
npm start
```

Abre `http://localhost:3000` — es la misma landing de siempre, con un botón nuevo
**"Comprar ahora"** en la sección de producto.

## 4. Que Mercado Pago pueda avisarte que ya pagaron (webhooks)

Mercado Pago necesita poder llamar a tu servidor por internet para avisarte "este pago
ya se aprobó". Localhost no es alcanzable desde internet, así que tienes dos opciones:

**Opción A — probar rápido con un túnel (ngrok):**

```bash
npx ngrok http 3000
```

Copia la URL pública que te da (`https://algo.ngrok-free.app`), ponla en `.env` como
`PUBLIC_BASE_URL`, reinicia el servidor, y registra
`https://algo.ngrok-free.app/api/webhook/mercadopago` como URL de notificaciones en tu
panel de Mercado Pago (*Tu negocio → Configuración → Notificaciones webhook*).

**Opción B — hosting real (recomendado antes de vender de verdad):** despliega esta
carpeta en Railway, Render, un VPS, etc. — cualquiera que te dé una URL `https://` fija
— y usa esa URL como `PUBLIC_BASE_URL` y en el webhook de Mercado Pago.

Sin uno de los dos, el botón de compra funciona y te manda a pagar, pero **el pedido se
quedará en estado "pending" para siempre** porque el aviso de "ya pagó" nunca llega.

## 5. Probar un pago (modo sandbox)

Con credenciales `TEST-...`, usa las tarjetas de prueba de Mercado Pago:

- Aprobada: `5031 7557 3453 0604`
- Rechazada: `5031 4332 1540 6351`
- Cualquier fecha futura de vencimiento, cualquier CVV de 3 dígitos, nombre `APRO` para
  forzar aprobación (ver la documentación de Mercado Pago para más nombres de prueba).

## 6. Reembolsos

```bash
curl -X POST http://localhost:3000/api/orders/<external_reference>/refund \
  -H "x-admin-key: TU_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{}'
```

Deja el body `{}` para reembolso total, o `{"amount": 30}` para uno parcial.

⚠️ **Este endpoint solo está protegido por una llave compartida (`ADMIN_KEY`) — no es
un sistema de autenticación real.** Sirve para probar el flujo, pero antes de operar con
clientes reales reemplázalo por un panel de administración con login real (ver
`PAGOKIT_PRODUCTION_CHECKLIST.md`).

## 7. Base de datos

SQLite en `db/la-taquera.sqlite` (se crea sola al arrancar, no se sube a git). Tablas:

- `orders` — cada pedido: referencia, cliente, monto, estado, id de pago de Mercado Pago.
- `webhook_events_processed` — evita procesar el mismo aviso de pago dos veces.
- `idempotency_keys` — registro de las llaves de idempotencia usadas al crear
  preferencias y reembolsos.

## 8. Estructura

```
server/
├── server.js                    # arranca todo, rutas de retorno de checkout
├── db/index.js                  # SQLite + queries de orders/webhooks/idempotencia
├── lib/mercadopago.js           # cliente del SDK oficial (lee MP_ACCESS_TOKEN)
├── lib/verifyMercadoPagoSignature.js  # verificación HMAC del webhook
├── routes/createPreference.js   # POST /create-preference
├── routes/webhookMercadoPago.js # POST /api/webhook/mercadopago
├── routes/orders.js             # GET /api/orders/:ref, POST /api/orders/:ref/refund
└── public/index.html            # la landing, con el botón "Comprar ahora"
```

## Nota sobre este entorno de pruebas

Esta sesión corre en un espacio de trabajo en la nube temporal — no tiene una URL
pública fija ni sigue corriendo después de que termina la sesión. Es perfecto para
armar y probar el código, pero para vender de verdad necesitas moverlo a un hosting
real (ver arriba). Antes de aceptar pagos reales, revisa
`PAGOKIT_PRODUCTION_CHECKLIST.md`.
