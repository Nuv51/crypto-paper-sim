# Backtest en frío 2025 — resultados

Periodo 2025-01-01 → 2026-01-01 (UTC). Dinero ficticio, parámetros sin tocar, corrida única. Es *cómo se habrían comportado estas reglas*, no una promesa ni una prueba de rentabilidad. Sesgos declarados en BACKTEST_2025.md.

## Referencias (comprar y mantener)

- BTC: -6.33% · ETH: -10.97% · Mercado (canasta de las 10 mayores): -9.18%

## Por simulador

| Simulador | ROI | Caída máx. | Sharpe | Operaciones | Comisiones (USDT) | ROI − BTC |
|---|---|---|---|---|---|---|
| Backtest 2025 · Simulador actual | -17.09% | -19.32% | -2.42 | 10,360 | 1,130 | -10.76 pp |
| Backtest 2025 · Simulador dinámico | -36.44% | -37.46% | -4.77 | 28,768 | 2,306 | -30.11 pp |
| Backtest 2025 · Simulador indexado | -27.67% | -50.86% | -0.19 | 491 | 47 | -21.34 pp |

## Backtest 2025 · Simulador actual

| Bot | Estrategia | ROI | Caída máx. | Operaciones | Comisiones | Estado |
|---|---|---|---|---|---|---|
| Carry spot-perpetuo | Carry · largo spot + corto perpetuo (delta-neutral), cobra funding | +0.17% | -1.09% | 543 | 28 | active |
| Stablecoins · peg | Stablecoins · reversión del peg (compra desvíos bajo 1.00, vende al volver) | -0.74% | -0.76% | 20 | 15 | active |
| DCA Majors | DCA · compras periódicas de monto fijo | -8.22% | -26.69% | 108 | 18 | active |
| Grid ETH | Grid · órdenes límite escalonadas en un rango | -33.40% | -42.37% | 1,059 | 145 | active |
| Reversión a la media | Reversión a la media · RSI + Bandas de Bollinger | -3.00% | -6.98% | 57 | 28 | active |
| Market making BTC | Market making · cotiza ±spread/2 con control de inventario | -77.27% | -77.83% | 6,890 | 567 | paused |
| Tendencia / Momentum | Tendencia · cruce de EMAs + momentum, trailing stop | -42.32% | -52.16% | 301 | 102 | active |
| Breakout dinámico | Breakout · ruptura de canal Donchian con stop ATR y sizing por riesgo | +10.25% | -19.34% | 210 | 56 | active |
| Señales ML | ML · regresión logística walk-forward (P de subida a 6 h) | -56.98% | -59.04% | 1,172 | 171 | active |
| Arbitraje XRP Bitso | Arbitraje XRP · Bitso ↔ Binance/KuCoin con fondos pre-posicionados (cota superior) | +0.00% | -0.00% | 0 | 0 | active |

## Backtest 2025 · Simulador dinámico

| Bot | Estrategia | ROI | Caída máx. | Operaciones | Comisiones | Estado |
|---|---|---|---|---|---|---|
| Carry BTC spot-perpetuo | Carry · largo spot + corto perpetuo (delta-neutral), cobra funding | -0.98% | -1.96% | 721 | 30 | active |
| Carry ETH spot-perpetuo | Carry · largo spot + corto perpetuo (delta-neutral), cobra funding | -0.37% | -1.34% | 734 | 20 | active |
| Stablecoins · peg | Stablecoins · reversión del peg (compra desvíos bajo 1.00, vende al volver) | -19.81% | -19.81% | 354 | 132 | active |
| DCA Majors+ | DCA · compras periódicas de monto fijo | -10.17% | -30.38% | 351 | 43 | active |
| Grid ETH | Grid · órdenes límite escalonadas en un rango | -52.97% | -54.45% | 4,082 | 225 | active |
| Grid BTC | Grid · órdenes límite escalonadas en un rango | -33.56% | -33.86% | 2,217 | 114 | active |
| Grid SOL | Grid · órdenes límite escalonadas en un rango | -34.68% | -34.80% | 3,370 | 135 | active |
| Reversión a la media | Reversión a la media · RSI + Bandas de Bollinger | -34.12% | -34.69% | 902 | 184 | active |
| Market making BTC | Market making · cotiza ±spread/2 con control de inventario | -61.46% | -61.70% | 5,934 | 293 | retired |
| Market making ETH | Market making · cotiza ±spread/2 con control de inventario | -51.16% | -51.85% | 3,766 | 150 | retired |
| Tendencia / Momentum | Tendencia · cruce de EMAs + momentum, trailing stop | -75.81% | -78.65% | 1,837 | 289 | active |
| Breakout dinámico | Breakout · ruptura de canal Donchian con stop ATR y sizing por riesgo | -89.35% | -90.45% | 1,758 | 303 | active |
| Señales ML | ML · regresión logística walk-forward (P de subida a 1 h) | -65.78% | -65.93% | 2,742 | 389 | retired |
| Arbitraje XRP Bitso | Arbitraje XRP · Bitso ↔ Binance/KuCoin con fondos pre-posicionados (cota superior) | +0.00% | -0.00% | 0 | 0 | active |

## Backtest 2025 · Simulador indexado

| Bot | Estrategia | ROI | Caída máx. | Operaciones | Comisiones | Estado |
|---|---|---|---|---|---|---|
| Índice Top-25 (capitalización) | Índice pasivo · rebalanceo periódico | -16.01% | -47.16% | 95 | 14 | active |
| Índice Top-50 (capitalización) | Índice pasivo · rebalanceo periódico | -18.44% | -47.59% | 122 | 14 | active |
| Índice Top-25 (igual peso) | Índice pasivo · rebalanceo periódico | -48.57% | -57.85% | 274 | 19 | active |
