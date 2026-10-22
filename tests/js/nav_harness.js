// Arnés mínimo: arma el HTML de los botones para cambiar de simulador.
// uso: node nav_harness.js <index.html> <registro.json> <id_actual> <carpeta_actual>   -> imprime JSON {html}
const fs = require('fs'), vm = require('vm');
const [, , page, regPath, myId, myDir] = process.argv;
const m = fs.readFileSync(page, 'utf8').match(/<script>([\s\S]*?)<\/script>/);
const ctx = { console, Intl, Date, Math, JSON, Promise, setTimeout, clearTimeout };
ctx.globalThis = ctx; ctx.__DASH_TEST__ = true; ctx.window = ctx;
ctx.document = { querySelectorAll: () => [], querySelector: () => null, addEventListener() {} };
ctx.location = { hash: '', hostname: 'x', pathname: '/' };
vm.createContext(ctx); vm.runInContext(m[1], ctx);
const list = JSON.parse(fs.readFileSync(regPath, 'utf8'));
process.stdout.write(JSON.stringify({ html: ctx.__dashApi.simNavHtml(list, myId, myDir) }));
