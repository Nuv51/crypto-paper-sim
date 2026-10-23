// Arnés mínimo: carga el <script> de web/index.html en modo prueba y renderiza la pestaña Comparar.
// uso: node compare_harness.js <index.html> <self.json> [otro.json ...]   -> imprime JSON {html, n}
const fs = require('fs'), vm = require('vm');
const [, , page, selfPath, ...others] = process.argv;
const m = fs.readFileSync(page, 'utf8').match(/<script>([\s\S]*?)<\/script>/);
const ctx = { console, Intl, Date, Math, JSON, Promise, setTimeout, clearTimeout };
ctx.globalThis = ctx; ctx.__DASH_TEST__ = true; ctx.window = ctx;
ctx.document = { querySelectorAll: () => [], querySelector: () => null, addEventListener() {} };
ctx.location = { hash: '', hostname: 'x' };
vm.createContext(ctx); vm.runInContext(m[1], ctx);
const load = p => JSON.parse(fs.readFileSync(p, 'utf8'));
const self = load(selfPath);
const st = { smCash: false, smPer: 'all', tx: { bot: '', ex: '', sym: '', side: '' }, txLimit: 100, sym: '', hz: '24', hidden: {},
             tab: 'comparar', cmpPer: process.env.CMP_PER || 'common', selfOrder: 0, others: others.map((p, i) => ({ d: load(p), order: i + 1 })) };
const html = ctx.__dashApi.buildPanels(self, null, st, 640).comparar;
process.stdout.write(JSON.stringify({ html }));
