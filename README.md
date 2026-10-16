# Simulador de bots cripto — precios reales, dinero ficticio

Paper trading para probar los 10 bots del proyecto **antes** de tocar capital real. Lee precios reales de mercado
(Binance, KuCoin, Bitso; APIs públicas), simula órdenes con comisiones y slippage, y publica un tablero con el
desempeño del portafolio y de cada bot. No envía órdenes a ningún exchange y no usa llaves de API.

> Resultados simulados no garantizan resultados futuros. Un backtest bonito es una hipótesis, no una prueba.

## Plan de corrida: ¿tiempo real o por intervalos?

**Por intervalos, no en tiempo real continuo.** Es a propósito:

- Los bots deciden **al cierre de cada vela de 1 hora** y sus órdenes se llenan desde la vela siguiente. No hay
  nada que reaccione segundo a segundo (eso requeriría datos de libro de órdenes que esta simulación no tiene).
- GitHub Actions ejecuta el simulador **cada hora** (minuto :07 UTC, cuando la vela ya cerró). Cada corrida procesa
  *todas* las velas cerradas que falten, en orden. Si una corrida se retrasa o falla, la siguiente se pone al día y el
  resultado es idéntico: la simulación no depende de *cuándo* corre.
- El estado completo viaja en `state/ledger.json` (rama `sim-data`). Si una corrida falla, el estado anterior no se toca.

| Qué | Cuándo | Cómo te enteras |
|---|---|---|
| Simulación | cada hora (:07 UTC) | — |
| Operaciones nuevas y alertas de riesgo | en cuanto ocurren (≤ 1 h de retraso) | ntfy (celular, reloj, tablet, computadora) |
| Falla de la corrida | al instante | ntfy de prioridad alta + GitHub Mobile |
| Resumen del portafolio y de cada bot | 08:00, 14:00 y 20:00 (CDMX/Monterrey) | ntfy |

Los bots que cotizan o rebalancean mucho (market making, grid) no mandan una notificación por orden: se resumen en una
línea por bot.

## Los 10 bots (numeración del glosario)

| # | Bot | Monedas | Plataforma | Cap. | Control de riesgo |
|---|-----|---------|-----------|-----:|-------------------|
| 1 | Carry spot-perpetuo | BTC | KuCoin | 15% | entra solo si el funding cubre costos; sale con 3 funding negativos; DD máx. 5% |
| 2 | Stablecoins · peg | USDC, FDUSD | Binance | 15% | solo desvíos ≥ 0.30%; sale ante de-peg real; DD máx. 2% |
| 3 | DCA | BTC, ETH | Bitso | 8% | solo alerta informativa a −45% (no tiene stop por diseño; el bot sigue) |
| 4 | Grid | ETH | Binance | 12% | rango ±10%, 16 niveles; liquida si rompe el rango; DD máx. 10% |
| 5 | Reversión a la media | BNB, ADA | KuCoin | 10% | stop 2–3% (ATR), TP 4%, DD máx. 10% |
| 6 | Market making | BTC | Binance | 8% | inventario 50% ± 20 pts; rebalancea a ±30; retira cotizaciones si la volatilidad sube; DD máx. 12% |
| 7 | Tendencia / Momentum | SOL, AVAX | Binance | 8% | stop 4%, trailing desde +5%, DD máx. 15% |
| 8 | Breakout dinámico | DOGE, LINK | Binance | 7% | riesgo 0.75%/operación, stop 1.75×ATR, DD máx. 17% |
| 9 | Señales ML | BTC, ETH, XRP | Binance | 5% | opera solo con P ≥ 0.60, stop 3%, reentrena cada 14 días; DD máx. 12% |
| 10 | Arbitraje XRP (Bitso ↔ Binance/KuCoin) | XRP | Bitso + Binance + KuCoin | 10% | umbral neto ≥ 0.30%, máx. 35% de desbalance de inventario |

Capital: 10,000 USDT ficticios × %; **98% desplegado y 2% de colchón**, como en el glosario.

### Qué hace cada uno de los bots nuevos (y qué NO demuestra)

**#1 Carry spot-perpetuo.** Compra BTC spot y vende en corto el perpetuo de KuCoin por la misma cantidad (delta-neutral):
no apuesta a la dirección, cobra el *funding*. Solo entra si el funding promedio de las últimas 3 liquidaciones cubre el
costo de entrar y salir (~0.4%) en 10 días (≈ 15% anual con las comisiones base) y sale tras 3 liquidaciones negativas.
Riesgos que modela: comisiones, basis, funding negativo y estrés de margen (cierra ambas patas a 80% de la garantía).
Lo que *no* modela: liquidación real del exchange, ADL, diferencias de precio entre el spot de Binance y el perpetuo de KuCoin
(el spot usa velas de Binance). **Con funding bajo no opera: es normal.**

**#2 Stablecoins.** Compra USDC o FDUSD cuando se desvían ≥ 0.30% *bajo* el peg y vende al volver. Con comisiones de 0.1% por
lado, un desvío de 0.15% (el extremo bajo del glosario) pierde dinero, por eso el umbral es 0.30%. Spot long-only: no
aprovecha desvíos *por encima* del peg. Puede pasar semanas sin operar; su valor es de bajo riesgo, no de rendimiento.

**#6 Market making.** Cotiza compra y venta ±0.15% alrededor del precio cada hora, con control de inventario. **Es una
aproximación**: con velas de 1 h no hay libro de órdenes, cola de prioridad ni latencia, que son lo que decide el resultado
de un market maker real. Sirve para ver el comportamiento del inventario, no para validar el negocio.

**#9 ML.** Regresión logística (solo numpy) que estima P(sube en 6 h), entrenada con las últimas 480 barras conocidas y
reentrenada cada 14 días (walk-forward). Registra su **acierto fuera de muestra** (si ronda 50% no hay edge). Es normal que
pase semanas sin superar el umbral de confianza de 0.60: eso también es un resultado válido.

**#10 Arbitraje XRP.** Cada corrida toma una foto del libro de Bitso (par XRP/USDT), Binance y KuCoin y calcula, para cada
ruta, el spread bruto y el neto de comisiones (Bitso USDT 0.36% taker, Binance y KuCoin 0.10%) y slippage. Es una **cota
superior optimista** (fondos pre-posicionados, ejecución instantánea, tamaño limitado a la punta del libro); solo ve una
foto por hora, no el flujo continuo, así que estima *cuántas veces* aparece una oportunidad. Con estas comisiones el spread
bruto necesario ronda 0.6–0.9%: si casi nunca aparece, la idea no se sostiene tal como está planteada.

## Riesgo automático (sin pasos manuales)

- **Por bot:** si un bot toca su límite de drawdown (columna de arriba) se **liquida, pausa 7 días y reanuda solo** con su
  máximo reiniciado. Si lo rompe **3 veces en 30 días** queda **retirado** (no vuelve a operar; se registra como resultado,
  no como pendiente). Al llegar al 80% del límite se registra un aviso. DCA (#3) solo emite una alerta informativa.
- **Global:** si el valor total del portafolio cae **10%** desde su máximo, se liquida todo, se pausa 7 días y todos reanudan
  solos (`PORTFOLIO_RISK` en `config.py`; forma parte de la huella de configuración).
- **Tablero:** la pestaña *Riesgo* muestra qué tan cerca está cada bot de su límite (marca al 80%), el freno global y el
  resultado por bot partido en *mercado* y *operación*; Summary tiene una ficha "Cerca del límite" y la tarjeta
  "¿Mercado o bots?" (por periodo). Mercado = posiciones del cierre anterior × movimiento del precio (los cortos de
  cobertura restan); bots = el resto (operar, comisiones, slippage, funding, arbitraje). Es una separación contable, no causal.
- Lo único que sigue siendo manual por naturaleza es la etapa de dinero real: depositar fondos, crear llaves API y mover capital entre exchanges.

**Solapamiento:** #7 y #8 son ambos "comprar fuerza"; #3, #6, #9 y #1 comparten BTC; #3, #4 y #9 comparten ETH. La pestaña
*Riesgo y solapamiento* mide la correlación real entre bots; si dos bots se mueven juntos, no diversifican.

## Cómo simula (todo conservador)

- Decide al **cierre** de cada vela; la orden se llena desde la vela **siguiente** (nunca en la misma).
- Mercado: apertura de la vela siguiente, con slippage adverso y comisión *taker*.
- Límite: solo se llena si el precio **cruza** el nivel (tocarlo no basta); comisión *maker*.
- Spot, solo largo, sin apalancamiento, salvo la pata corta del perpetuo del carry (2x, con garantía propia).
- Comisiones (verificadas 2026-10-14/16): Binance 0.100%/0.100%, KuCoin spot 0.100%/0.100% (nivel base, Clase A),
  KuCoin perpetuos 0.02%/0.06% (nivel base, **sin verificar**), Bitso MXN 0.600%/0.780% (tier < 20,000) y Bitso USDT
  0.300%/0.360%. Edita `sim/exchanges.py`; bajan con el volumen y cambian con el tiempo.
- Contabilidad: `equity = efectivo inicial + P&L realizado + P&L no realizado` se verifica en las pruebas, también para las patas
  del perpetuo, el funding y las capturas de arbitraje.

## Fuentes de datos (verificadas desde GitHub Actions el 2026-10-16)

| Dato | Fuente | Estado |
|---|---|---|
| Velas spot (todos los bots) | Binance `data-api.binance.vision` | funciona |
| Perpetuo y funding (#1) | KuCoin Futures `api-futures.kucoin.com` | funciona |
| Foto del libro XRP (#10) | Bitso `api.bitso.com`, Binance `bookTicker`, KuCoin `level1` | funciona (KuCoin `level1` sin verificar) |
| Futuros de Binance | `fapi.binance.com` | **bloqueado** (HTTP 451 desde IPs de EE. UU.): por eso el carry usa KuCoin |
| Futuros de Bybit | `api.bybit.com` | bloqueado (403) |

Si alguna fuente obligatoria falla, la corrida termina con código 2, el estado anterior no se toca y la siguiente se pone
al día. La foto de Bitso/KuCoin es opcional: si falla, solo se pierde esa muestra.

## Ejecución automática con GitHub Actions

`.github/workflows/simulate.yml` corre el simulador cada hora (y a mano: **Actions → simulate → Run workflow**).
Guarda en la rama **`sim-data`**: `binance/state/ledger.json` (estado), `binance/data/*.json` (tablero) y
`binance/index.html` (el tablero). Si falla, `status.json` explica el motivo y la corrida sale en rojo.

- **Reiniciar la simulación:** Run workflow → `fresh = true`. Hace falta al cambiar bots o parámetros: la configuración
  tiene una huella y una corrida con una configuración distinta *se niega* a continuar el estado guardado (no se afinan
  parámetros a mitad de una prueba hacia adelante). El estado anterior queda en `state/ledger.prev.json`.
- **Prueba sin red:** `source = synthetic` (datos inventados; guarda aparte, en `synthetic/`).
- **Avisos al celular, reloj, tablet y computadora (ntfy):** instala la app *ntfy* (gratis), suscríbete a un tema difícil de
  adivinar y guárdalo como secreto del repo `NTFY_TOPIC` (Settings → Secrets and variables → Actions). El nombre del tema
  funciona como contraseña: cualquiera que lo conozca puede leer los avisos (aquí solo hay datos de una simulación).
  Con eso llegan: operaciones y alertas de riesgo (`simulate.yml`), fallas, y el resumen de las 08:00, 14:00 y 20:00 hora
  de CDMX (`digest.yml`; para cambiar las horas edita su `cron`, que va en UTC). En un reloj, activa el reenvío de
  notificaciones de la app del celular.
- **Tablero web:** Settings → Pages → Branch `sim-data` → `/ (root)`; queda en `https://<usuario>.github.io/crypto-paper-sim/binance/`.
  La pestaña **Summary** (la primera) es la vista minimalista: valor del portafolio, dona por bot, dona por activo
  (solo posiciones largas spot; con opción de incluir efectivo), rendimiento por estrategia y por bot, y crecimiento
  contra Bitcoin y Ethereum con selector de periodo (Día, Semana, Mes, 3 meses, Año, Inicio) y tabla comparativa, más seis
  métricas de resumen. Los periodos largos usan velas de BTC y ETH que cada corrida trae de Binance (horarias de ~32 días y
  diarias de 365); el portafolio solo se muestra en un periodo cuando ya lleva ese tiempo corriendo (no se inventa historial).
  La pestaña Bots agrupa los bots por tipo de estrategia. Las demás pestañas siguen igual. Las familias de estrategia están en `sim/export.py` (`FAMILIES`), no en `config.py`, para que reagrupar
  no cambie la huella de configuración ni reinicie la simulación.
- **Historial de la rama de datos:** se compacta solo cada ~300 corridas (el estado completo va en `ledger.json`).
- Los repos públicos pierden los flujos programados tras 60 días sin actividad. El flujo intenta mantenerse activo (mejor
  esfuerzo); si pasa, se reactivan desde la pestaña Actions. El resumen diario avisa si el simulador lleva más de 3 h sin correr.
- Todo es simulación con dinero ficticio y sin llaves de API.

## Inicio rápido (en tu computadora)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python run.py replay --days 120            # historial REAL (API públicas), a toda velocidad
streamlit run dashboard.py                 # tablero (lee data/paper.db)

python run.py live --poll 60               # forward test: una vela nueva por hora, se puede detener y reanudar
python run.py report                       # resumen en consola
python run.py replay --days 120 --source synthetic --db data/synth.db --fresh   # datos INVENTADOS, solo para probar código
```

El `replay` no puede medir el bot #10 (no existe historial del libro de órdenes): solo el forward test lo mide.
Opcional: `export CMC_API_KEY=...` activa la verificación cruzada de precio con CoinMarketCap en modo live
(copia `.env.example`; nunca pongas llaves en el código).

## Archivos

```
config.py            capital, monedas, parámetros y límites de riesgo por bot
run.py               CLI: replay | live | report
cloud_step.py        un paso incremental para la nube (lo usa GitHub Actions)
dashboard.py         Streamlit + Plotly (uso local)
web/index.html       tablero web de un solo archivo (lo publica la rama sim-data)
scripts/ci_run.sh    una corrida de CI: estado, tablero, avisos
scripts/digest.py    textos de las notificaciones (operaciones nuevas, resumen, tabla)
scripts/probe.py     sondeo de qué APIs alcanza GitHub (se usó para elegir las fuentes)
sim/broker.py        wallet virtual: comisiones, slippage, límite, reservas, patas fuera de spot
sim/bots.py          las 10 estrategias
sim/engine.py        bucle de replay/live, control de riesgo, persistencia
sim/data.py          Binance, KuCoin futuros, foto de Bitso, feed sintético, CoinMarketCap
sim/cloud.py         paso de nube, huella de configuración
sim/forecast.py      estimación de tendencia (con cono de incertidumbre)
sim/metrics.py       métricas y solapamiento
sim/ledger.py        SQLite
tests/               80 pruebas
```

## Pruebas

`python -m pytest -q` verifica: contabilidad (identidad de equity, efectivo nunca negativo, comisiones, patas sintéticas),
reglas de ejecución, **ausencia de look-ahead** (indicadores y resultados idénticos con datos truncados y completos, en los
10 bots), determinismo, controles de riesgo, que detener y reanudar da exactamente el mismo resultado, que el carry es
neutral a la dirección y cobra funding, que las stablecoins no "atrapan cuchillos" en un de-peg, que el ML no opera bajo su
umbral y entrena solo con etiquetas ya conocidas, que el arbitraje descuenta todos los costos, y las fuentes de datos contra
una capa HTTP simulada con el formato real de cada API.

## Límites que debes tener presentes

- **Sin libro de órdenes:** el slippage es fijo por bot (1–10 bps); en una altcoin ilíquida o en una caída fuerte será peor.
- **Bitso:** se aplican sus comisiones, pero el precio del DCA viene de pares USDT de Binance (aproximación; no incluye USD/MXN).
- **Velas de 1h:** no se sabe qué pasó dentro de la vela. Los stops se evalúan al cierre y se ejecutan en la apertura siguiente.
- **Overfitting:** no ajustes parámetros mirando el mismo periodo que luego usas para "demostrar" que funciona.
  Separa un tramo de validación, prueba en distintos regímenes (alcista, bajista, lateral) y desconfía de lo que solo funciona en uno.
- **Un periodo no es evidencia:** 120 días de un mercado son una sola muestra. El forward test es la prueba más honesta;
  regla sugerida: no juzgar ningún bot con menos de ~30 días o ~30 operaciones cerradas.
- **Datos sintéticos:** los genera un modelo simple; sirven para probar el código, no para juzgar estrategias.

## Cuando pases a cuentas reales (no es parte de este simulador)

| | Binance | KuCoin | Bitso |
|---|---|---|---|
| Autenticación | HMAC-SHA256 sobre la query + header `X-MBX-APIKEY` | HMAC-SHA256 en base64 + passphrase + versión de llave | HMAC-SHA256 en el header `Authorization` con nonce |
| Límites de rate | por peso de petición e IP | por pool de recursos según nivel VIP | por endpoint |
| Mercado | spot, margen, futuros (bloqueado desde EE. UU.) | spot, margen, futuros | solo spot (MXN, USD, USDT…) |

Revisa la documentación oficial de cada uno para los límites vigentes. Empieza con llaves **sin permiso de retiro**, con
whitelist de IP, y con capital que estés dispuesto a perder por completo.
