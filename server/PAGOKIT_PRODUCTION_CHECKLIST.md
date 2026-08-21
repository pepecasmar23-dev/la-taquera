# Checklist antes de aceptar pagos reales

Esta integración se armó siguiendo `SECURITY_RULES.md` del plugin PagoKit
(`payment-advisor`). Antes de usarla con clientes y dinero reales, revisa cada punto:

## Credenciales

- [ ] Cambiar `MP_ACCESS_TOKEN` de `TEST-...` a tu Access Token real `APP_USR-...`.
- [ ] Confirmar que `MP_WEBHOOK_SECRET` corresponde a la URL de webhook que registraste
      en el panel de Mercado Pago para producción (no la de pruebas).
- [ ] `ADMIN_KEY` es una cadena larga y aleatoria (no `changeme`, no una palabra fácil).
- [ ] `.env` real NUNCA se sube a git, ni se comparte por Slack/WhatsApp/captura de pantalla.

## Hosting y red

- [ ] La app corre detrás de HTTPS (Mercado Pago exige HTTPS para `notification_url` en
      producción).
- [ ] `PUBLIC_BASE_URL` apunta a tu dominio real de producción.
- [ ] La URL de notificaciones webhook en el panel de Mercado Pago apunta a
      `https://tu-dominio.com/api/webhook/mercadopago`.

## Autenticación de administrador (reembolsos)

- [ ] **Reemplazar el header `x-admin-key` por autenticación real** antes de operar con
      clientes reales: login de administrador, roles, idealmente 2FA.
- [ ] Registrar auditoría (quién reembolsó qué pedido y cuándo) — hoy no existe.

## Webhooks

- [ ] Confirmar que la verificación de firma (`x-signature`) está activa y que el
      servidor rechaza (401) firmas inválidas — probado en este proyecto, pero vuelve a
      probarlo contra el endpoint de producción antes de lanzar.
- [ ] Confirmar que `webhook_events_processed` sigue funcionando bajo carga (SQLite es
      suficiente para el volumen actual; si el negocio crece mucho, considera Postgres).

## Legal / datos personales

- [ ] **México — LFPDPPP aplica.** Publica un aviso de privacidad indicando qué datos
      recolectas (nombre, correo) y para qué.
- [ ] **CFDI 4.0** — la emisión de facturas fiscales por cada venta es responsabilidad
      tuya; Mercado Pago no factura por ti (no es Merchant of Record).
- [ ] Revisa con un contador/abogado local tus obligaciones fiscales antes de vender
      formalmente.

## Buenas prácticas generales

- [ ] Rate limiting en `/create-preference` y `/api/orders/*/refund` (por ejemplo con
      `express-rate-limit`) para evitar abuso.
- [ ] Monitoreo de errores (Sentry o similar) en vez de solo `console.error`.
- [ ] Backups periódicos de `db/la-taquera.sqlite` (o migrar a una base de datos
      administrada con backups automáticos si el volumen crece).
- [ ] Probar el flujo completo de punta a punta con una compra real de bajo monto antes
      de anunciar la tienda públicamente.

---
Información de Mercado Pago verificada al 2026-05-20 según el catálogo de PagoKit;
las tarifas y la disponibilidad de métodos de pago pueden haber cambiado — confírmalas
en tu panel de Mercado Pago antes de lanzar.
