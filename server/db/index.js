// db/index.js
// SQLite (better-sqlite3) — sin ORM, suficiente para el volumen de este negocio.
// Tablas: orders, webhook_events_processed (dedup de webhooks), idempotency_keys.

const path = require('path');
const Database = require('better-sqlite3');

const DB_PATH = process.env.DB_PATH || path.join(__dirname, 'la-taquera.sqlite');
const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');

db.exec(`
CREATE TABLE IF NOT EXISTS orders (
  id                 TEXT PRIMARY KEY,
  external_reference TEXT UNIQUE NOT NULL,
  customer_name      TEXT,
  customer_email     TEXT,
  -- Datos de envío (solo se piden para productos físicos, ej. merch). Rule 11
  -- sigue aplicando: nada de tarjeta, identificaciones ni fecha de nacimiento
  -- aquí — eso lo captura Mercado Pago directamente en su propia pantalla.
  shipping_json      TEXT,
  items_json         TEXT NOT NULL,
  amount             REAL NOT NULL,
  currency           TEXT NOT NULL DEFAULT 'MXN',
  status             TEXT NOT NULL DEFAULT 'pending', -- pending | approved | rejected | refunded | cancelled | in_process | amount_mismatch
  mp_payment_id      TEXT,
  mp_preference_id   TEXT,
  created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_orders_mp_payment_id ON orders(mp_payment_id);

-- Rule 9: replay protection via event-id dedup for Mercado Pago webhooks.
CREATE TABLE IF NOT EXISTS webhook_events_processed (
  event_id     TEXT PRIMARY KEY,
  event_type   TEXT,
  processed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- Rule 4: idempotency keys must be cryptographic UUIDs (crypto.randomUUID()),
-- persisted here so retries of the same logical request can be deduplicated.
CREATE TABLE IF NOT EXISTS idempotency_keys (
  key        TEXT PRIMARY KEY,
  purpose    TEXT NOT NULL, -- 'create_preference' | 'refund'
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
`);

// ---------- orders ----------

function insertPendingOrder({ id, externalReference, customerName, customerEmail, shippingJson, itemsJson, amount, currency }) {
  db.prepare(`
    INSERT INTO orders (id, external_reference, customer_name, customer_email, shipping_json, items_json, amount, currency, status)
    VALUES (@id, @externalReference, @customerName, @customerEmail, @shippingJson, @itemsJson, @amount, @currency, 'pending')
  `).run({ id, externalReference, customerName, customerEmail, shippingJson: shippingJson || null, itemsJson, amount, currency });
}

function setPreferenceId(externalReference, mpPreferenceId) {
  db.prepare(`
    UPDATE orders SET mp_preference_id = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
    WHERE external_reference = ?
  `).run(mpPreferenceId, externalReference);
}

function getOrderByExternalReference(externalReference) {
  return db.prepare('SELECT * FROM orders WHERE external_reference = ?').get(externalReference);
}

function getOrderByMpPaymentId(mpPaymentId) {
  return db.prepare('SELECT * FROM orders WHERE mp_payment_id = ?').get(mpPaymentId);
}

function updateOrderStatusByExternalReference(externalReference, { status, mpPaymentId }) {
  db.prepare(`
    UPDATE orders
    SET status = ?, mp_payment_id = COALESCE(?, mp_payment_id), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
    WHERE external_reference = ?
  `).run(status, mpPaymentId || null, externalReference);
}

// ---------- webhook event dedup (Rule 9) ----------

function hasProcessedEvent(eventId) {
  return !!db.prepare('SELECT 1 FROM webhook_events_processed WHERE event_id = ?').get(eventId);
}

function markEventProcessed(eventId, eventType) {
  db.prepare(`
    INSERT OR IGNORE INTO webhook_events_processed (event_id, event_type) VALUES (?, ?)
  `).run(eventId, eventType || null);
}

// ---------- idempotency keys (Rule 4) ----------

function recordIdempotencyKey(key, purpose) {
  db.prepare(`INSERT OR IGNORE INTO idempotency_keys (key, purpose) VALUES (?, ?)`).run(key, purpose);
}

module.exports = {
  db,
  insertPendingOrder,
  setPreferenceId,
  getOrderByExternalReference,
  getOrderByMpPaymentId,
  updateOrderStatusByExternalReference,
  hasProcessedEvent,
  markEventProcessed,
  recordIdempotencyKey,
};
