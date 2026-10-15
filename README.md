# Simulador de bots cripto — precios reales, dinero ficticio

Paper trading para probar los bots del proyecto **antes** de tocar capital real. Lee velas reales de
mercado, simula órdenes con comisiones y slippage, y guarda todo en SQLite para el dashboard.
No envía órdenes a ningún exchange y no necesita llaves de trading.

> Resultados simulados no garantizan resultados futuros. Un backtest bonito es una hipótesis, no una prueba.

## Inicio rápido

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python run.py replay --days 120            # historial REAL de Binance (API pública), a toda velocidad
streamlit run dashboard.py                 # tablero (lee data/paper.db)

python run.py live --poll 60               # forward test: una vela nueva por hora, se puede detener y reanudar
python run.py report                       # resumen en consola
python run.py replay --days 120 --source synthetic --db data/synth.db --fresh   # datos INVENTADOS, solo para probar código
```

Opcional: `export CMC_API_KEY=...` activa la verificación cruzada de precio con CoinMarketCap en modo live
(copia `.env.example`; nunca pongas llaves en el código).

## Cómo simula (todo conservador)

- Decide al **cierre** de cada vela; la orden se llena desde la vela **siguiente** (nunca en la misma).
- Mercado: apertura de la vela siguiente, con slippage adverso y comisión *taker*.
- Límite: solo se llena si el precio **cruza** el nivel (tocarlo no basta); comisión *maker*.
- Spot, solo largo, sin apalancamiento. Las órdenes límite reservan efectivo/cantidad (no se gasta dos veces).
- Comisiones (verificadas 2026-10-14): Binance 0.100%/0.100%, KuCoin 0.100%/0.100% (nivel base, Clase A),
  Bitso MXN 0.600%/0.780% (tier < 20,000). Edita `sim/exchanges.py`; bajan con el volumen y cambian con el tiempo.
- Contabilidad: `equity = efectivo inicial + P&L realizado + P&L no realizado` se verifica en las pruebas.
  El P&L por venta usa costo promedio ponderado e incluye comisiones.

## Bots incluidos (numeración del glosario)

| # | Bot | Monedas | Plataforma | Riesgo | Control de riesgo |
|---|-----|---------|-----------|--------|-------------------|
| 3 | DCA | BTC, ETH | Bitso | bajo | alerta de revisión manual a -45% |
| 4 | Grid | ETH | Binance | medio | rango ±10%, 16 niveles; liquida si rompe el rango; DD máx. 10% |
| 5 | Reversión a la media | BNB, ADA | KuCoin | medio | stop 2–3% (ATR), TP 4%, DD máx. 10% |
| 7 | Tendencia / Momentum | SOL, AVAX | Binance | alto | stop 4%, trailing desde +5%, DD máx. 15% |
| 8 | Breakout dinámico | DOGE, LINK | Binance | alto | riesgo 0.75%/operación, stop 1.75×ATR, pausa 7 días a -17% |

Capital: 10,000 USDT ficticios × % del glosario (10/12/10/8/7%). El resto queda como reserva para los 5 bots que aún
no existen (arbitraje spot-futuro, stablecoins, market making, ML, arbitraje XRP cross-exchange): necesitan funding
rates, libro de órdenes o varios exchanges a la vez, datos que esta versión todavía no consume.

**Solapamiento:** #7 y #8 son ambos "comprar fuerza". La pestaña *Riesgo y solapamiento* mide la correlación entre
bots y marca monedas compartidas; si dos bots se mueven juntos, no diversifican.

## Archivos

```
config.py            capital, monedas, parámetros y límites de riesgo por bot
run.py               CLI: replay | live | report
dashboard.py         Streamlit + Plotly
sim/broker.py        wallet virtual: comisiones, slippage, límite, reservas
sim/bots.py          las 5 estrategias
sim/engine.py        bucle de replay/live, control de riesgo, persistencia
sim/data.py          Binance público, feed sintético, CoinMarketCap
sim/forecast.py      estimación de tendencia (con cono de incertidumbre)
sim/metrics.py       métricas y solapamiento
sim/ledger.py        SQLite
tests/               21 pruebas
```

## Pruebas

`python -m pytest -q` verifica: contabilidad (identidad de equity, efectivo nunca negativo, comisiones), reglas
de ejecución, **ausencia de look-ahead** (indicadores idénticos con datos truncados y completos), determinismo,
controles de riesgo, que detener y reanudar el modo live da exactamente el mismo resultado, y el feed de Binance
contra una capa HTTP simulada (paginación, caché, descarte de la vela en formación).

## Límites que debes tener presentes

- **Sin libro de órdenes:** el slippage es fijo por bot (2–10 bps); en una altcoin ilíquida o en una caída fuerte será peor.
- **Bitso:** se aplican sus comisiones, pero el precio viene de pares USDT de Binance (aproximación; no incluye USD/MXN).
- **Velas de 1h:** no se sabe qué pasó dentro de la vela. Los stops se evalúan al cierre y se ejecutan en la apertura siguiente.
- **Overfitting:** no ajustes parámetros mirando el mismo periodo que luego usas para "demostrar" que funciona.
  Separa un tramo de validación, prueba en distintos regímenes (alcista, bajista, lateral) y desconfía de lo que solo funciona en uno.
- **Un periodo no es evidencia:** 120 días de un mercado son una sola muestra. El modo live (forward test) es la prueba más honesta.
- **Datos sintéticos:** los genera un modelo simple; sirven para probar el código, no para juzgar estrategias.

## Cuando pases a cuentas reales (no es parte de este simulador)

| | Binance | KuCoin | Bitso |
|---|---|---|---|
| Autenticación | HMAC-SHA256 sobre la query + header `X-MBX-APIKEY` | HMAC-SHA256 en base64 + passphrase + versión de llave | HMAC-SHA256 en el header `Authorization` con nonce |
| Límites de rate | por peso de petición e IP | por pool de recursos según nivel VIP | por endpoint |
| Mercado | spot, margen, futuros | spot, margen, futuros | solo spot (MXN, USD, USDT…) |

Revisa la documentación oficial de cada uno para los límites vigentes. Empieza con llaves **sin permiso de retiro**, con
whitelist de IP, y con capital que estés dispuesto a perder por completo.

---

## Modo nube (tarea programada + tablero publicado)

Cada corrida de una tarea programada es una sesión nueva **sin disco compartido**, así que el estado viaja en archivos
del artefacto publicado (el tablero web):

```
artefacto/
├─ index.html            tablero (solo dibuja; lee data/*.json)
├─ code/bundle.json      todo el código (make_bundle.py lo genera)
├─ state/ledger.json     estado completo del simulador (snapshot del ledger)
└─ data/dashboard.json · data/status.json   lo que muestra el tablero
```

Flujo de cada corrida: leer `code/bundle.json` + `state/ledger.json` → desempaquetar → `python cloud_step.py --state … --out …`
→ republicar `index.html` con los 3 JSON nuevos. Códigos de salida: **0** ok · **1** error · **2** sin datos/red
(solo se publica `status.json`; el estado anterior no se toca).

* La simulación **no depende de cuándo corre**: cada corrida procesa todas las velas cerradas pendientes, en orden. Correr cada
  hora, 6 h o 1 vez al día da el mismo resultado; solo cambia qué tan fresco está el tablero.
* Datos: velas de Binance (API pública, sin llaves). Hay que permitir `data-api.binance.vision` y `api.binance.com` en
  Configuración → Capacidades → acceso de red; si no, la corrida termina con código 2 y el tablero lo avisa.
* Prueba sin red: `python cloud_step.py --source synthetic --out out` (datos inventados; el tablero lo marca en rojo).
* No usa llaves de API de ningún exchange (solo lectura de precios públicos).
* Tras cambiar código: `python make_bundle.py code/bundle.json` y publicar el bundle junto con `web/index.html`.
