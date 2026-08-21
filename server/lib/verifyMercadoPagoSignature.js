// lib/verifyMercadoPagoSignature.js
//
// Verifica la firma HMAC-SHA256 que Mercado Pago envía en el header `x-signature`
// de cada webhook, siguiendo el algoritmo documentado oficialmente:
// https://www.mercadopago.com.mx/developers/es/docs/your-integrations/notifications/webhooks
//
//   x-signature: ts=1704908010,v1=618c85345248dd820d5fd456117c2ca3ca55c7ea472e6d2b3c0a90c7db5e1de1
//   x-request-id: 3e3435f9-...
//
//   manifest = `id:{data.id};request-id:{x-request-id};ts:{ts};`
//   firma esperada = HMAC_SHA256(manifest, MP_WEBHOOK_SECRET) en hex
//
// `data.id` se toma del QUERY STRING de la URL de notificación (Mercado Pago lo
// agrega automáticamente), no del cuerpo. Si trae letras, deben ir en minúsculas.
//
// Rule 5: esta verificación se hace sobre el manifest derivado del signature header +
// query string, NO requiere el cuerpo crudo para el cálculo del HMAC en sí, pero el
// handler igual debe leer el body como texto crudo antes de parsear JSON (evita que un
// middleware de parseo silencioso rompa la verificación si el proveedor cambia el
// esquema en el futuro) y para no perder bytes si se necesita reprocesar.
//
// Rule 9: se valida además que el timestamp `ts` no sea más viejo que la tolerancia
// (300s) para mitigar ataques de repetición (replay), en combinación con el
// dedup por event id que hace el caller.

const crypto = require('crypto');

const DEFAULT_TOLERANCE_SECONDS = 300;

function parseSignatureHeader(headerValue) {
  // headerValue ejemplo: "ts=1704908010,v1=618c8534..."
  const parts = {};
  String(headerValue || '')
    .split(',')
    .forEach((chunk) => {
      const [key, ...rest] = chunk.split('=');
      if (!key) return;
      parts[key.trim()] = rest.join('=').trim();
    });
  return parts;
}

/**
 * @param {object} params
 * @param {string} params.xSignature - header 'x-signature'
 * @param {string} params.xRequestId - header 'x-request-id'
 * @param {string} params.dataId - 'data.id' tomado del query string de la notification_url
 * @param {string} params.secret - MP_WEBHOOK_SECRET
 * @param {number} [params.toleranceSeconds]
 * @returns {{ valid: boolean, reason?: string }}
 */
function verifyMercadoPagoSignature({ xSignature, xRequestId, dataId, secret, toleranceSeconds }) {
  if (!secret) {
    return { valid: false, reason: 'missing_webhook_secret' };
  }
  if (!xSignature || !xRequestId || !dataId) {
    return { valid: false, reason: 'missing_headers_or_data_id' };
  }

  const { ts, v1 } = parseSignatureHeader(xSignature);
  if (!ts || !v1) {
    return { valid: false, reason: 'malformed_signature_header' };
  }

  const tolerance = toleranceSeconds || DEFAULT_TOLERANCE_SECONDS;
  const tsNum = Number(ts);
  if (!Number.isFinite(tsNum)) {
    return { valid: false, reason: 'malformed_timestamp' };
  }
  const nowSeconds = Math.floor(Date.now() / 1000);
  if (Math.abs(nowSeconds - tsNum) > tolerance) {
    return { valid: false, reason: 'timestamp_out_of_tolerance' };
  }

  const normalizedDataId = /^[a-zA-Z0-9]+$/.test(dataId) ? String(dataId).toLowerCase() : String(dataId);
  const manifest = `id:${normalizedDataId};request-id:${xRequestId};ts:${ts};`;

  const expected = crypto.createHmac('sha256', secret).update(manifest).digest('hex');

  const expectedBuf = Buffer.from(expected, 'hex');
  const receivedBuf = Buffer.from(String(v1), 'hex');
  if (expectedBuf.length !== receivedBuf.length || !crypto.timingSafeEqual(expectedBuf, receivedBuf)) {
    return { valid: false, reason: 'signature_mismatch' };
  }

  return { valid: true };
}

module.exports = { verifyMercadoPagoSignature, parseSignatureHeader };
