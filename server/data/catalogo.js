// data/catalogo.js
//
// Catálogo autoritativo de precios. Es la ÚNICA fuente de verdad del servidor.
//
// El navegador nunca manda precios: manda el id del producto y la cantidad, y
// aquí se resuelve cuánto cuesta. Si el cliente manda un `unit_price` en el
// cuerpo de la petición, se ignora — antes se usaba tal cual, lo que permitía
// comprar cualquier producto por $1.
//
// Los ids coinciden con los que usa el catálogo del sitio
// (catalogo.html -> ?product=gorra-crema, etc.).

const CURRENCY = 'MXN';

// Tope por línea: nadie pide 500 gorras por la web; si pasa, es un error o un abuso.
const MAX_QUANTITY_PER_ITEM = 20;

const CATALOGO = {
  'salsa-150':              { title: 'Salsa La Taquera 150 ml',                 price: 79 },
  'playera-blanca-pecho':   { title: 'Playera blanca, logo al pecho',           price: 449 },
  'playera-negra-pecho':    { title: 'Playera negra, logo al pecho',            price: 449 },
  'playera-blanca-espalda': { title: 'Playera blanca, ajo en la espalda',       price: 479 },
  'playera-negra-espalda':  { title: 'Playera negra, ajo en la espalda',        price: 479 },
  'gorra-crema':            { title: 'Gorra crema, wordmark bordado',           price: 429 },
  'gorra-negra':            { title: 'Gorra negra, mascota bordada',            price: 429 },
  'tote-natural':           { title: 'Tote bag natural, manta de algodón',      price: 249 },
  'stickers-pack':          { title: 'Pack de 4 stickers',                      price: 99 },
};

/**
 * Convierte lo que mandó el navegador en líneas de pedido con precio del servidor.
 *
 * Entrada esperada: [{ id: 'gorra-crema', quantity: 2 }, ...]
 * Cualquier otro campo del cliente (title, unit_price) se descarta.
 *
 * @param {any} items
 * @returns {{ ok: true, items: Array<{id:string,title:string,quantity:number,unit_price:number}>, amount:number, currency:string }
 *          | { ok: false, error: string }}
 */
function resolverItems(items) {
  if (!Array.isArray(items) || items.length === 0) {
    return { ok: false, error: 'items es requerido y debe tener al menos un elemento.' };
  }
  if (items.length > 20) {
    return { ok: false, error: 'Demasiadas líneas en el pedido.' };
  }

  const resueltos = [];
  for (const it of items) {
    const id = it && typeof it.id === 'string' ? it.id.trim() : '';
    const producto = CATALOGO[id];
    if (!producto) {
      return { ok: false, error: `Producto desconocido: ${id || '(sin id)'}` };
    }

    const quantity = Number(it.quantity);
    if (!Number.isInteger(quantity) || quantity < 1 || quantity > MAX_QUANTITY_PER_ITEM) {
      return { ok: false, error: `Cantidad inválida para ${id} (permitido: 1 a ${MAX_QUANTITY_PER_ITEM}).` };
    }

    resueltos.push({
      id,
      title: producto.title,
      quantity,
      unit_price: producto.price, // <- del catálogo, nunca del cliente
    });
  }

  const amount = resueltos.reduce((sum, it) => sum + it.unit_price * it.quantity, 0);
  return { ok: true, items: resueltos, amount, currency: CURRENCY };
}

/** Precio de un producto, o null si el id no existe. */
function precioDe(id) {
  const p = CATALOGO[id];
  return p ? p.price : null;
}

module.exports = { CATALOGO, CURRENCY, MAX_QUANTITY_PER_ITEM, resolverItems, precioDe };
