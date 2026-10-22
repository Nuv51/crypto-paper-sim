# Backtest en frío 2026 — resultados

Periodo 2026-01-01 → 2026-10-10 (inclusive) (UTC). Dinero ficticio, parámetros sin tocar, corrida única. Es *cómo se habrían comportado estas reglas*, no una promesa ni una prueba de rentabilidad. Sesgos declarados en BACKTEST_2025.md.

## Referencias (comprar y mantener)

- BTC: -5.32% · ETH: -15.65% · Mercado (canasta de las 10 mayores): -8.20%

## Por simulador

| Simulador | ROI | Caída máx. | Sharpe | Operaciones | Comisiones (USDT) | ROI − BTC |
|---|---|---|---|---|---|---|
| Reserva 2026 · Simulador actual | -10.06% | -13.80% | -2.20 | 7,929 | 873 | -4.74 pp |
| Reserva 2026 · Simulador dinámico | -18.57% | -22.92% | -3.17 | 18,779 | 1,666 | -13.25 pp |
| Reserva 2026 · Simulador indexado | -4.11% | -46.55% | 0.14 | 332 | 41 | 1.21 pp |

## Reserva 2026 · Simulador actual

| Bot | Estrategia | ROI | Caída máx. | Operaciones | Comisiones | Estado |
|---|---|---|---|---|---|---|
| Carry spot-perpetuo | Carry · largo spot + corto perpetuo (delta-neutral), cobra funding | +0.00% | -0.00% | 0 | 0 | active |
| Stablecoins · peg | Stablecoins · reversión del peg (compra desvíos bajo 1.00, vende al volver) | -0.04% | -0.10% | 4 | 3 | active |
| DCA Majors | DCA · compras periódicas de monto fijo | +6.09% | -9.50% | 82 | 11 | active |
| Grid ETH | Grid · órdenes límite escalonadas en un rango | -3.88% | -14.61% | 560 | 79 | active |
| Reversión a la media | Reversión a la media · RSI + Bandas de Bollinger | -2.44% | -7.60% | 54 | 26 | active |
| Market making BTC | Market making · cotiza ±spread/2 con control de inventario | -57.57% | -59.02% | 5,789 | 477 | active |
| Tendencia / Momentum | Tendencia · cruce de EMAs + momentum, trailing stop | -29.30% | -54.45% | 202 | 64 | active |
| Breakout dinámico | Breakout · ruptura de canal Donchian con stop ATR y sizing por riesgo | -10.35% | -26.79% | 184 | 55 | active |
| Señales ML | ML · regresión logística walk-forward (P de subida a 6 h) | -39.15% | -40.96% | 1,054 | 157 | active |
| Arbitraje XRP Bitso | Arbitraje XRP · Bitso ↔ Binance/KuCoin con fondos pre-posicionados (cota superior) | +0.00% | -0.00% | 0 | 0 | active |

## Reserva 2026 · Simulador dinámico

| Bot | Estrategia | ROI | Caída máx. | Operaciones | Comisiones | Estado |
|---|---|---|---|---|---|---|
| Carry BTC spot-perpetuo | Carry · largo spot + corto perpetuo (delta-neutral), cobra funding | -1.05% | -1.48% | 402 | 17 | active |
| Carry ETH spot-perpetuo | Carry · largo spot + corto perpetuo (delta-neutral), cobra funding | -0.13% | -0.66% | 445 | 7 | active |
| Stablecoins · peg | Stablecoins · reversión del peg (compra desvíos bajo 1.00, vende al volver) | -4.80% | -4.80% | 101 | 38 | active |
| DCA Majors+ | DCA · compras periódicas de monto fijo | +14.28% | -24.52% | 198 | 21 | active |
| Grid ETH | Grid · órdenes límite escalonadas en un rango | -4.56% | -19.36% | 2,504 | 177 | active |
| Grid BTC | Grid · órdenes límite escalonadas en un rango | -13.77% | -22.36% | 1,939 | 101 | active |
| Grid SOL | Grid · órdenes límite escalonadas en un rango | -6.83% | -16.65% | 1,356 | 62 | active |
| Reversión a la media | Reversión a la media · RSI + Bandas de Bollinger | -23.90% | -26.19% | 800 | 163 | active |
| Market making BTC | Market making · cotiza ±spread/2 con control de inventario | -45.62% | -45.98% | 4,148 | 205 | retired |
| Market making ETH | Market making · cotiza ±spread/2 con control de inventario | -29.93% | -31.13% | 2,668 | 106 | retired |
| Tendencia / Momentum | Tendencia · cruce de EMAs + momentum, trailing stop | -52.26% | -59.76% | 1,774 | 297 | active |
| Breakout dinámico | Breakout · ruptura de canal Donchian con stop ATR y sizing por riesgo | -70.74% | -78.76% | 1,434 | 324 | paused |
| Señales ML | ML · regresión logística walk-forward (P de subida a 1 h) | -32.31% | -32.40% | 1,010 | 148 | retired |
| Arbitraje XRP Bitso | Arbitraje XRP · Bitso ↔ Binance/KuCoin con fondos pre-posicionados (cota superior) | +0.00% | -0.00% | 0 | 0 | active |

## Reserva 2026 · Simulador indexado

| Bot | Estrategia | ROI | Caída máx. | Operaciones | Comisiones | Estado |
|---|---|---|---|---|---|---|
| Índice Top-25 (capitalización) | Índice pasivo · rebalanceo periódico | -10.74% | -47.18% | 65 | 12 | active |
| Índice Top-50 (capitalización) | Índice pasivo · rebalanceo periódico | -10.57% | -47.25% | 68 | 11 | active |
| Índice Top-25 (igual peso) | Índice pasivo · rebalanceo periódico | +9.00% | -46.41% | 199 | 18 | active |
