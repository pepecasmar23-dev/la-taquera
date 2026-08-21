// routes/webhookMercadoPago.js
// POST /api/webhook/mercadopago
//
// Recibe las notificaciones de pago de Mercado Pago ("ya pagó", pendiente, rechazado,
// reembolsado, etc). Esta es la única fuente de verdad para actualizar el estado de
// un pedido — el frontend nunca decide por sí mismo que un pago se completó.
//
// Rule 3 + Rule 5: se verifica la firma x-signature ANTES de tocar el body, y el body
// se consume en crudo (express.raw) — nunca express.json() antes de verificar.
// Rule 6: solo se registra event.id / event.type, nunca el payload completo.
// Rule 9: dedup por event id (tabla webhook_events_processed) + tolerancia de timestamp
//         de 5 minutos dentro de la propia verificación de firma.
// Rule 10: el body crudo está limitado a 256kb antes de intentar verificar/parsear.

const express = require('express');
const { verifyMercadoPagoSignature } = require('../lib/verifyMercadoPagoSignature');
const { paymentClient } = require('../lib/mercadopago');
const {
  hasProcessedEvent,
  markEventProcessed,
  getOrderByExternalReference,
  updateOrderStatusByExternalReference,
} = require('../db/index');

const router = express.Router();

// Mapea el status de Mercado Pago al status interno que usamos en `orders`.
function mapMpStatusToOrderStatus(mpStatus) {
  switch (mpStatus) {
    case 'approved':
      return 'approved';
    case 'pending':
    case 'in_process':
    case 'authorized':
      return 'pending';
    case 'rejected':
      return 'rejected';
    case 'cancelled':
      return 'cancelled';
    case 'refunded':
    case 'charged_back':
      return 'refunded';
    default:
      return 'pending';
  }
}

router.post(
  '/api/webhook/mercadopago',
  // Rule 5 + Rule 10: raw body únicamente en esta ruta, con límite de tamaño.
  express.raw({ type: '*/*', limit: '256kb' }),
  async (req, res) => {
    try {
      const xSignature = req.get('x-signature');
      const xRequestId = req.get('x-request-id');
      // Mercado Pago agrega `data.id` (y `type`) como query string a la notification_url.
      const dataId = req.query['data.id'] || req.query['id'];

      const verification = verifyMercadoPagoSignature({
        xSignature,
        xRequestId,
        dataId,
        secret: process.env.MP_WEBHOOK_SECRET,
      });

      if (!verification.valid) {
        console.warn('[webhook/mercadopago] firma inválida:', verification.reason);
        // 401 y no procesamos nada más — evita que alguien falsifique un "ya pagó".
        return res.status(401).json({ error: 'invalid_signature' });
      }

      // Recién ahora, con la firma ya verificada, parseamos el body crudo.
      let body = {};
      try {
        body = req.body && req.body.length ? JSON.parse(req.body.toString('utf8')) : {};
      } catch (_e) {
        body = {};
      }

      const eventId = String(body.id || `${dataId}:${req.query.type || body.type || 'unknown'}`);
      const eventType = body.type || req.query.type || 'unknown';

      // Rule 6: solo id/type en logs, nunca el payload completo.
      console.log('[webhook/mercadopago] evento recibido', { eventId, eventType });

      // Rule 9: dedup — si ya procesamos este evento, respondemos 200 sin repetir efectos.
      if (hasProcessedEvent(eventId)) {
        return res.status(200).json({ ok: true, deduped: true });
      }

      // Solo nos interesan eventos de pago; confirmamos el ack para el resto.
      if (eventType !== 'payment' && req.query.type !== 'payment') {
        markEventProcessed(eventId, eventType);
        return res.status(200).json({ ok: true, ignored: eventType });
      }

      if (!dataId) {
        markEventProcessed(eventId, eventType);
        return res.status(200).json({ ok: true, ignored: 'missing_data_id' });
      }

      // Nunca confiamos en el status que venga en el body de la notificación:
      // siempre volvemos a consultar el pago directo a la API de Mercado Pago.
      const payment = await paymentClient.get({ id: dataId });

      const externalReference = payment.external_reference;
      if (externalReference) {
        const order = getOrderByExternalReference(externalReference);
        if (order) {
          const newStatus = mapMpStatusToOrderStatus(payment.status);
          updateOrderStatusByExternalReference(externalReference, {
            status: newStatus,
            mpPaymentId: String(payment.id),
          });
        } else {
          console.warn('[webhook/mercadopago] pago sin pedido correspondiente', { externalReference });
        }
      }

      markEventProcessed(eventId, eventType);
      return res.status(200).json({ ok: true });
    } catch (err) {
      console.error('[webhook/mercadopago] error procesando webhook:', err && err.message ? err.message : err);
      // 200 para evitar reintentos agresivos de MP ante un error transitorio nuestro
      // ya registrado; si prefieres que MP reintente, cambia a 500.
      return res.status(200).json({ ok: false });
    }
  }
);

module.exports = router;
