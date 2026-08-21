// server.js — punto de entrada del servidor de LA TAQUERA.
require('dotenv').config();

const path = require('path');
const express = require('express');
const cors = require('cors');

// Falla rápido y con un mensaje claro si falta configuración crítica,
// en vez de arrancar "a medias" y fallar de forma confusa más tarde.
const REQUIRED_ENV = ['MP_ACCESS_TOKEN', 'MP_WEBHOOK_SECRET', 'ADMIN_KEY'];
const missing = REQUIRED_ENV.filter((k) => !process.env[k]);
if (missing.length) {
  console.warn(
    `[server] Faltan variables de entorno: ${missing.join(', ')}. ` +
      'Copia .env.example a .env y complétalo (ver README.md). El servidor arrancará ' +
      'igual para que puedas probar rutas que no las necesiten, pero los pagos reales fallarán.'
  );
}

const app = express();
app.use(cors());

// IMPORTANTE: el webhook de Mercado Pago se registra ANTES que cualquier
// express.json() global, porque necesita el body crudo (Rule 5) para poder
// verificar la firma de forma confiable.
app.use(require('./routes/webhookMercadoPago'));

app.use(require('./routes/createPreference'));
app.use(require('./routes/orders'));

app.use(express.static(path.join(__dirname, 'public')));

function renderReturnPage({ title, heading, message, tone }) {
  const toneColor = tone === 'error' ? '#C42A1F' : tone === 'warn' ? '#E3A63C' : '#2E7D32';
  return `<!DOCTYPE html>
<html lang="es-MX">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>${title} — LA TAQUERA</title>
<style>
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
    background:#F2E9D8;color:#221A14;font-family:-apple-system,Segoe UI,Roboto,sans-serif;padding:24px;}
  .card{max-width:440px;text-align:center;background:#FAF5EA;border-radius:20px;padding:40px 32px;
    box-shadow:0 20px 40px -20px rgba(34,26,20,.35);}
  .badge{display:inline-block;width:56px;height:56px;border-radius:50%;background:${toneColor};margin-bottom:20px;}
  h1{font-size:26px;margin:0 0 12px;}
  p{font-size:15px;line-height:1.6;color:rgba(34,26,20,.75);margin:0 0 24px;}
  #status{font-size:13px;color:rgba(34,26,20,.55);margin-bottom:20px;}
  a.btn{display:inline-block;background:#C42A1F;color:#FAF5EA;text-decoration:none;padding:14px 28px;
    border-radius:999px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;font-size:13px;}
</style>
</head>
<body>
  <div class="card">
    <div class="badge"></div>
    <h1>${heading}</h1>
    <p>${message}</p>
    <div id="status">Verificando estado del pedido…</div>
    <a class="btn" href="/">Volver a la tienda</a>
  </div>
  <script>
    const params = new URLSearchParams(window.location.search);
    const ref = params.get('external_reference');
    const statusEl = document.getElementById('status');
    if (ref) {
      fetch('/api/orders/' + encodeURIComponent(ref))
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          if (!data) { statusEl.textContent = 'No pudimos confirmar el estado del pedido.'; return; }
          const map = { approved: '✅ Pago confirmado.', pending: '⏳ Pago pendiente.', in_process: '⏳ Pago en proceso.',
            rejected: '❌ Pago rechazado.', cancelled: '❌ Pedido cancelado.', refunded: '↩️ Pedido reembolsado.' };
          statusEl.textContent = (map[data.status] || ('Estado: ' + data.status)) + ' Referencia: ' + data.external_reference;
        })
        .catch(() => { statusEl.textContent = 'No pudimos confirmar el estado del pedido.'; });
    } else {
      statusEl.textContent = '';
    }
  </script>
</body>
</html>`;
}

app.get('/checkout/success', (req, res) => {
  res.send(
    renderReturnPage({
      title: 'Pago recibido',
      heading: '¡Ya pagaste!',
      message: 'Gracias por tu pedido. En cuanto Mercado Pago confirme el pago verás el estado actualizado abajo.',
      tone: 'ok',
    })
  );
});

app.get('/checkout/pending', (req, res) => {
  res.send(
    renderReturnPage({
      title: 'Pago pendiente',
      heading: 'Tu pago está pendiente',
      message: 'Recibimos tu pedido, pero el pago todavía se está procesando (por ejemplo, si pagaste en OXXO). Te avisaremos cuando se confirme.',
      tone: 'warn',
    })
  );
});

app.get('/checkout/failure', (req, res) => {
  res.send(
    renderReturnPage({
      title: 'Pago no completado',
      heading: 'No se pudo completar el pago',
      message: 'Tu pago no se completó. Puedes intentarlo de nuevo desde la tienda o escribirnos por WhatsApp si el problema sigue.',
      tone: 'error',
    })
  );
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`[server] LA TAQUERA corriendo en http://localhost:${PORT}`);
});
