// lib/mercadopago.js
// Cliente único del SDK oficial de Mercado Pago (mercadopago v2).
// El Access Token SOLO vive aquí, leído de process.env — nunca hardcodeado (Rule 1).

const { MercadoPagoConfig, Preference, Payment, PaymentRefund } = require('mercadopago');

if (!process.env.MP_ACCESS_TOKEN) {
  // eslint-disable-next-line no-console
  console.warn(
    '[mercadopago] MP_ACCESS_TOKEN no está definido. Copia .env.example a .env y agrega tu Access Token real.'
  );
}

const client = new MercadoPagoConfig({
  accessToken: process.env.MP_ACCESS_TOKEN || 'TEST-MISSING-TOKEN',
  options: { timeout: 8000 },
});

const preferenceClient = new Preference(client);
const paymentClient = new Payment(client);
const refundClient = new PaymentRefund(client);

module.exports = { client, preferenceClient, paymentClient, refundClient };
