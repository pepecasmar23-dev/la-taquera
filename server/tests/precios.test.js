// tests/precios.test.js
//
// Comprueba que el precio lo pone el servidor y no el navegador.
// Se ejecuta con:  npm test    (desde la carpeta server/)
//
// No necesita base de datos ni credenciales: prueba data/catalogo.js en aislado.

const { resolverItems, CATALOGO } = require('../data/catalogo');

let fallos = 0;
function check(nombre, condicion, extra) {
  console.log((condicion ? '  ok   ' : '  FALLA') + ' ' + nombre + (extra ? '  -> ' + extra : ''));
  if (!condicion) fallos++;
}

// --- Lo importante: un cliente malicioso no puede fijar el precio ------------
let r = resolverItems([{ id: 'salsa-150', quantity: 1, unit_price: 1, title: 'Salsa gratis' }]);
check('ignora el unit_price que manda el cliente', r.ok && r.items[0].unit_price === 79, 'precio = ' + (r.ok ? r.items[0].unit_price : r.error));
check('ignora el title que manda el cliente', r.ok && r.items[0].title === 'Salsa La Taquera 150 ml');
check('el total lo calcula el servidor', r.ok && r.amount === 79, 'total = ' + r.amount);

// --- Varias líneas ----------------------------------------------------------
r = resolverItems([{ id: 'gorra-crema', quantity: 2 }, { id: 'stickers-pack', quantity: 3 }]);
check('suma correctamente varias líneas', r.ok && r.amount === 429 * 2 + 99 * 3, 'total = ' + r.amount);

// --- Entradas inválidas -----------------------------------------------------
check('rechaza un id que no existe', !resolverItems([{ id: 'salsa-gratis', quantity: 1 }]).ok);
check('rechaza una línea sin id', !resolverItems([{ quantity: 1, unit_price: 5 }]).ok);
check('rechaza cantidad 0', !resolverItems([{ id: 'salsa-150', quantity: 0 }]).ok);
check('rechaza cantidad negativa', !resolverItems([{ id: 'salsa-150', quantity: -3 }]).ok);
check('rechaza cantidad decimal', !resolverItems([{ id: 'salsa-150', quantity: 1.5 }]).ok);
check('rechaza cantidad absurda', !resolverItems([{ id: 'salsa-150', quantity: 9999 }]).ok);
check('rechaza lista vacía', !resolverItems([]).ok);
check('rechaza algo que no es lista', !resolverItems('salsa-150').ok);
check('rechaza undefined', !resolverItems(undefined).ok);

// --- Coherencia con el catálogo del sitio -----------------------------------
const idsDelSitio = [
  'gorra-crema', 'gorra-negra',
  'playera-blanca-espalda', 'playera-blanca-pecho',
  'playera-negra-espalda', 'playera-negra-pecho',
  'stickers-pack', 'tote-natural',
];
check('los 8 productos del catálogo web existen en el servidor',
  idsDelSitio.every((id) => resolverItems([{ id, quantity: 1 }]).ok));
check('todos los precios del catálogo son números positivos',
  Object.values(CATALOGO).every((p) => Number.isFinite(p.price) && p.price > 0));

console.log(fallos === 0 ? '\nTodo bien.' : '\n' + fallos + ' fallo(s).');
process.exit(fallos ? 1 : 0);
