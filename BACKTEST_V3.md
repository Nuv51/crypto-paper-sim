# Simulador en frío V3 — Núcleo con filtro de tendencia · PRE-REGISTRO

Se escribe y se sube **antes** de correr nada. Todo cambio posterior se anota al final en "Cambios posteriores" y **no cuenta** como evidencia a favor.
Dinero ficticio. Es "cómo se habrían comportado estas reglas", no una promesa de rentabilidad.

## 0. Honestidad previa (léase primero)

V3 **no se diseñó a ciegas**: nace del análisis de resultados de V2 sobre 2019-2024 (los mismos años en que ahora se prueba) y de 2025-2026.
Sabemos que los satélites y las estables no aportaron, que el índice y el DCA concentran la caída, y que el carry fue lo más consistente.
Por tanto, esta corrida **no es validación fuera de muestra**: es una prueba de coherencia (¿hace el filtro lo que se supone, y no más?).
La única validación limpia es el **paper trading en vivo** hacia adelante. Los criterios de abajo se fijan ahora para evitar reinterpretarlos después.

## 1. Hipótesis (3)

- **H1 · Filtro de tendencia.** Comprar/mantener la parte "beta" (DCA e índice) solo cuando BTC cierra por encima de su media de 200 días reduce la caída máxima frente al mismo portafolio sin filtro (**V3-ref**, el control), sin destruir el rendimiento ajustado por riesgo.
- **H2 · Quitar lo que no aportó.** Sin satélites ni estables, con más peso al carry y 10 % en efectivo, V3 cuesta menos y cae menos que V2 en la mayoría de los años.
- **H3 · Frente a BTC.** V3 cae menos que BTC comprar-y-mantener en casi todos los años (como V2), sin gastar más de 1 % del capital en costos.

## 2. Estructura (10,000 USDT al 1 de enero de cada año)

| Bot | Estrategia | Capital | Filtro |
|---|---|---|---|
| w01_dca | DCA semanal BTC+ETH (parámetros de V2) | 20 % | V3 sí / ref no |
| w04_index_cap25 | Índice Top-25 por capitalización, tope 30 %, rebalanceo cada 90 días | 30 % | V3 sí / ref no |
| w02_carry_btc | Largo spot + corto perpetuo BTC | 25 % (V2: 12.5 %) | — |
| w03_carry_eth | Carry ETH, umbral 3 % APR | 15 % (V2: 7.5 %) | — |
| efectivo | sin rendimiento | 10 % | — |

Sin carry en 2019 (no hay perpetuos de Binance antes de 2020-01): ese 40 % queda en efectivo (50 % del capital sin trabajar), y cuenta en ROI y caída.
Universo, deslizamiento y parámetros de cada bot: **idénticos a V2** (`config_v2_<año>.py`); se genera con `scripts/make_config_v3.py`. No se afina nada.
Los pesos 20/30/25/15/10 se fijaron aquí a priori; no se probaron alternativas.

**Filtro (btc_sma):** una vez por día UTC, ON si el último cierre diario de BTCUSDT (23:00 del día previo) > media de los 200 cierres diarios previos;
con historial insuficiente, OFF. Al apagarse el bot liquida a efectivo; al encenderse se reinicia (el índice conserva el suministro de cada moneda).
La serie larga se carga aparte para que el calentamiento de 200 días no sea requisito de cada moneda. Sin mirar al futuro (probado en `tests/test_v3.py`).
Con la media de 200 días el filtro puede dejar el DCA/índice fuera durante rallies tempranos (whipsaw); es un costo asumido, no un defecto a corregir.

## 3. Ejecución

Mismo motor y mismas reglas que V2: decisión al cierre de la vela de 1 h, ejecución en la apertura siguiente con comisión y deslizamiento. Doce corridas
independientes: 2019-2024 × {V3, V3-ref}. Cada una arranca con 10,000 el 1 de enero. ROI y caída son sobre los 10,000 completos (el efectivo cuenta).
Corrida única (guardia en el flujo `backtest-v3`; `repetir` solo por fallo técnico, anotado aquí).

**Reserva:** 2025-2026 se corre aparte (`grupo=reserva`), una sola vez, **después** de la reserva de V2, con el carry de KuCoin como en V1. Se reporta, no decide.

## 4. Criterios de éxito (fijados de antemano; sobre 2019-2024)

| # | Criterio | Se cumple si |
|---|---|---|
| D1 | Caída controlada | caída máxima de V3 ≤ 35 % en **cada** uno de los 6 años |
| D2 | Consistencia | ROI de V3 > 0 en ≥ 4 de 6 años |
| D3 | Costos bajos | comisiones + deslizamiento de V3 < 1.0 % del capital inicial en cada año |
| D4 | Frente a BTC (H3) | caída máx. de V3 < la de BTC comprar-y-mantener en ≥ 5 de 6 años |
| D5 | El filtro aporta (H1) | caída máx. V3 < V3-ref en ≥ 4 de 6 años **y** ROI/|caída máx.| (Calmar) V3 > V3-ref en ≥ 4 de 6 |
| D6 | Mejor que V2 (H2) | caída máx. V3 < V2 en ≥ 4 de 6 años **y** costos V3 < V2 en los 6 |

Un criterio incumplido se reporta como incumplido; no se reinterpreta. Si D2 falla, V3 no se considera rentable por sí mismo.
Si D5 falla, el filtro no pasa a la versión en vivo. Con 6 años (un ciclo) ninguna conclusión es estadísticamente fuerte.
Se reportan también, sin criterio: ROI encadenado, Sharpe, porcentaje del tiempo con el filtro apagado por año, y V3 vs BTC en ROI (se espera perder en años alcistas).

## 5. Limitaciones y sesgos declarados

- **Contaminación** (ver §0): estructura y pesos salen de mirar estos años. D1 y D3 son umbrales elegidos conociendo el resultado de V2 (peor caída 45 %, costos 1.4-2.5 %).
- **Supervivencia, carry con datos de Binance (2020-2024), liquidez constante, sin impuestos, universo 2019 de 15 monedas:** como en `BACKTEST_V2_2019_2024.md` §6.
- **Un solo parámetro del filtro (200 días)**: es el valor convencional, no se probó otro. Probar varios sobre estos años sería sobreajuste.
- **Las estables y el arbitraje XRP no se evalúan** en V3 (V2 mostró aporte ≈ 0).
- La comparación con V2 usa los resultados de V2 ya publicados (misma semilla de datos; costos y caídas de `backtest_v2/analysis/portfolio_by_year.csv`).

## 6. Después

Si D5 se cumple, V3 pasa a paper trading en vivo (junto a los simuladores actuales, sin tocarlos) y se mide hacia adelante con los mismos criterios.
Si no se cumple, queda solo V3-ref (núcleo sin filtro) como candidata a vivo.

## 7. Cambios posteriores

(ninguno antes de correr. 2026-10-22: las 12 corridas principales y la reserva V2 terminaron sin fallos ni repeticiones; resultados en `BACKTEST_V3_RESULTADOS.md`. La reserva V3 2025-2026 (`grupo=reserva`) **no** se ha corrido y, dado D5, solo tendría sentido para V3-ref.)
