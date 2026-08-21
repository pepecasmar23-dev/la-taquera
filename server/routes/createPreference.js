// routes/createPreference.js
// POST /create-preference
// Crea una preferencia de Checkout Pro (redirige al cliente a la página de pago
// alojada por Mercado Pago) y guarda un pedido "pending" en la base de datos.

const crypto = require('crypto');
const express = require('express');
const { preferenceClient } = require('../lib/mercadopago');
const { insertPendingOrder, setPreferenceId, recordIdempotencyKey } = require('../db/index');

const router = express.Router();

function isNonEmptyString(v) {
  return typeof v === 'string' && v.trim().length > 0;
}

router.post('/create-preference', express.json(), async (req, res) => {
  try {
    const { items, customer } = req.body || {};

    if (!Array.isArray(items) || items.length === 0) {
      return res.status(400).json({ error: 'items es requerido y debe tener al menos un elemento.' });
    }
    for (const it of items) {
      if (!isNonEmptyString(it.title) || !(Number(it.quantity) > 0) || !(Number(it.unit_price) > 0)) {
        return res.status(400).json({ error: 'Cada item requiere title, quantity y unit_price válidos.' });
      }
    }
    // Rule 11: PII mínima — solo lo necesario para contactar y enviar el pedido.
    // Nunca tarjeta, identificaciones ni fecha de nacimiento: eso lo captura
    // Mercado Pago directamente en su propia pantalla de pago.
    const customerName = customer && isNonEmptyString(customer.name) ? customer.name.trim().slice(0, 120) : null;
    const customerEmail = customer && isNonEmptyString(customer.email) ? customer.email.trim().slice(0, 160) : null;
    const customerPhone = customer && isNonEmptyString(customer.phone) ? customer.phone.trim().slice(0, 20) : null;

    // Datos de envío: opcionales a nivel de esquema (la salsa se puede pedir
    // solo con nombre+correo), pero el checkout de merch los pide todos.
    const shipping = customer && typeof customer === 'object' ? {
      address: isNonEmptyString(customer.address) ? customer.address.trim().slice(0, 200) : null,
      colonia: isNonEmptyString(customer.colonia) ? customer.colonia.trim().slice(0, 120) : null,
      city: isNonEmptyString(customer.city) ? customer.city.trim().slice(0, 120) : null,
      state: isNonEmptyString(customer.state) ? customer.state.trim().slice(0, 120) : null,
      postalCode: isNonEmptyString(customer.postalCode) ? customer.postalCode.trim().slice(0, 10) : null,
    } : null;
    const hasShipping = shipping && Object.values(shipping).some(Boolean);

    const externalReference = crypto.randomUUID();
    const orderId = crypto.randomUUID();
    const amount = items.reduce((sum, it) => sum + Number(it.unit_price) * Number(it.quantity), 0);
    const currency = 'MXN';

    insertPendingOrder({
      id: orderId,
      externalReference,
      customerName,
      customerEmail,
      shippingJson: hasShipping ? JSON.stringify({ phone: customerPhone, ...shipping }) : null,
      itemsJson: JSON.stringify(items),
      amount,
      currency,
    });

    const baseUrl = (process.env.PUBLIC_BASE_URL || `${req.protocol}://${req.get('host')}`).replace(/\/$/, '');

    // Rule 4: idempotency key must be a cryptographic UUID — never Date.now()/Math.random().
    const idempotencyKey = crypto.randomUUID();
    recordIdempotencyKey(idempotencyKey, 'create_preference');

    const preference = await preferenceClient.create({
      body: {
        items: items.map((it) => ({
          title: String(it.title).slice(0, 250),
          quantity: Number(it.quantity),
          unit_price: Number(it.unit_price),
          currency_id: currency,
        })),
        payer: customerEmail ? {
          name: customerName || undefined,
          email: customerEmail,
          phone: customerPhone ? { area_code: '', number: customerPhone } : undefined,
          address: shipping && shipping.postalCode ? {
            zip_code: shipping.postalCode,
            street_name: shipping.address || undefined,
          } : undefined,
        } : undefined,
        external_reference: externalReference,
        notification_url: `${baseUrl}/api/webhook/mercadopago`,
        back_urls: {
          success: `${baseUrl}/checkout/success`,
          failure: `${baseUrl}/checkout/failure`,
          pending: `${baseUrl}/checkout/pending`,
        },
        auto_return: 'approved',
        statement_descriptor: 'LA TAQUERA',
      },
      requestOptions: { idempotencyKey },
    });

    setPreferenceId(externalReference, preference.id);

    return res.json({
      init_point: preference.init_point,
      sandbox_init_point: preference.sandbox_init_point,
      external_reference: externalReference,
    });
  } catch (err) {
    // No se registra el objeto completo del error si pudiera contener datos sensibles del request.
    console.error('[create-preference] error:', err && err.message ? err.message : err);
    return res.status(502).json({ error: 'No se pudo crear la preferencia de pago. Intenta de nuevo.' });
  }
});

module.exports = router;
