// routes/orders.js
// GET  /api/orders/:externalReference          — estado del pedido (para el frontend)
// POST /api/orders/:externalReference/refund    — reembolso (protegido con x-admin-key)

const crypto = require('crypto');
const express = require('express');
const { refundClient } = require('../lib/mercadopago');
const { getOrderByExternalReference, updateOrderStatusByExternalReference, recordIdempotencyKey } = require('../db/index');

const router = express.Router();

function toPublicOrder(order) {
  if (!order) return null;
  return {
    external_reference: order.external_reference,
    status: order.status,
    amount: order.amount,
    currency: order.currency,
    created_at: order.created_at,
    updated_at: order.updated_at,
  };
}

router.get('/api/orders/:externalReference', (req, res) => {
  const order = getOrderByExternalReference(req.params.externalReference);
  if (!order) return res.status(404).json({ error: 'not_found' });
  return res.json(toPublicOrder(order));
});

// ---------------------------------------------------------------------------
// ADVERTENCIA (léela antes de usar esto con clientes reales):
// Esta ruta mueve dinero real (reembolsos) y solo está protegida por una llave
// compartida (ADMIN_KEY) en un header. Es un placeholder mínimo para que puedas
// probar el flujo — NO es un sistema de autenticación de administrador real.
// Antes de operar con clientes reales, reemplázalo por autenticación real
// (sesión de admin, roles, 2FA, registro de auditoría de quién reembolsó qué).
// Ver PAGOKIT_PRODUCTION_CHECKLIST.md.
// ---------------------------------------------------------------------------
router.post('/api/orders/:externalReference/refund', express.json(), async (req, res) => {
  try {
    const providedKey = req.get('x-admin-key');
    const adminKey = process.env.ADMIN_KEY;

    if (!adminKey || adminKey === 'changeme') {
      return res.status(500).json({
        error: 'admin_key_not_configured',
        message: 'Configura ADMIN_KEY en .env con un valor real antes de usar reembolsos.',
      });
    }
    if (!providedKey || providedKey !== adminKey) {
      return res.status(401).json({ error: 'unauthorized' });
    }

    const order = getOrderByExternalReference(req.params.externalReference);
    if (!order) return res.status(404).json({ error: 'order_not_found' });
    if (!order.mp_payment_id) {
      return res.status(409).json({ error: 'order_has_no_payment', message: 'Este pedido aún no tiene un pago asociado.' });
    }
    if (order.status === 'refunded') {
      return res.status(200).json({ ok: true, already_refunded: true });
    }

    // Rule 4: idempotency key criptográfica, nunca Date.now()/Math.random().
    const idempotencyKey = crypto.randomUUID();
    recordIdempotencyKey(idempotencyKey, 'refund');

    const amount = req.body && req.body.amount ? Number(req.body.amount) : undefined; // omitir = reembolso total

    await refundClient.create({
      payment_id: order.mp_payment_id,
      body: amount ? { amount } : {},
      requestOptions: { idempotencyKey },
    });

    updateOrderStatusByExternalReference(order.external_reference, { status: 'refunded' });

    return res.json({ ok: true });
  } catch (err) {
    console.error('[refund] error:', err && err.message ? err.message : err);
    return res.status(502).json({ error: 'refund_failed' });
  }
});

module.exports = router;
