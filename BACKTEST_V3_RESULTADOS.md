# Simulador en frío V3 — Núcleo con filtro de tendencia · RESULTADOS (+ reserva V2 2025-2026)

Pre-registro: `BACKTEST_V3.md` (subido antes de correr; commit `ee0a42d`). Corridas únicas en GitHub Actions: flujo `backtest-v3` (rama `backtest-v3`, 12 corridas: V3 y V3-ref × 2019-2024) y `backtest-v2-reserva` (rama `backtest-v2-reserva`). Sin fallos técnicos ni repeticiones. Análisis: `backtest_v3/analysis/` (`analyze_v3.py`, `figs_v3.py`, `build_v3.py`). Dinero ficticio; ROI y caída sobre los 10,000 USDT completos (el efectivo cuenta).

## 1. Veredicto contra los criterios (2019-2024)

| # | Criterio | Resultado | |
|---|---|---|---|
| D1 | Caída máx. de V3 ≤ 35 % cada año | −47.3 % en 2021; los otros cinco entre −0.5 % y −29.1 % | ✗ |
| D2 | ROI V3 > 0 en ≥ 4 de 6 años | 4 de 6 (2019 −3.2 %, 2022 −0.4 %) | ✓ |
| D3 | Costos < 1.0 % del capital cada año | solo 2019 (0.50 %) y 2022 (0.68 %); 2021: 3.38 % | ✗ |
| D4 | Caída máx. < BTC en ≥ 5 de 6 | 6 de 6 | ✓ |
| D5 | Filtro aporta: caída V3 < ref en ≥ 4 **y** Calmar V3 > ref en ≥ 4 | caída menor 5 de 6; Calmar mayor 2 de 6 | ✗ |
| D6 | Caída V3 < V2 en ≥ 4 **y** costos V3 < V2 en 6 | caída menor 5 de 6; costos menores 5 de 6 (2021 mayor) | ✗ |

V3 cumple **2 de 6**. Por §6 del pre-registro, el filtro **no** pasa a vivo; la candidata es V3-ref.

## 2. Por año

| Año | V3 ROI / caída / costos | V3-ref ROI / caída / costos | V2 ROI / caída | BTC ROI | Días filtro ON |
|---|---|---|---|---|---|
| 2019 | −3.2 % / −29.1 % / 0.50 % | +4.0 % / −43.3 % / 0.26 % | +1.9 % / −43.9 % | +94.4 % | n/d |
| 2020 | +75.3 % / −14.8 % / 1.22 % | +130.1 % / −31.7 % / 0.96 % | +128.3 % / −32.9 % | +302.0 % | 77 % |
| 2021 | +27.5 % / −47.3 % / 3.38 % | +90.4 % / −44.9 % / 1.11 % | +88.8 % / −45.0 % | +59.8 % | 71 % |
| 2022 | −0.4 % / −0.5 % / 0.68 % | −29.7 % / −31.4 % / 0.89 % | −31.9 % / −33.8 % | −64.2 % | 0 % |
| 2023 | +18.8 % / −11.0 % / 1.11 % | +44.2 % / −14.4 % / 0.71 % | +42.5 % / −16.8 % | +155.6 % | 80 % |
| 2024 | +20.0 % / −18.0 % / 1.30 % | +36.5 % / −21.7 % / 0.58 % | +33.4 % / −23.1 % | +121.3 % | 80 % |
| Encadenado | +208 % | +531 % | +468 % | +2,428 % | |

## 3. Lectura

1. **El filtro hace lo que se diseñó (evitar el año malo) y cuesta casi todo el resto.** En 2022 estuvo apagado todo el año (−0.4 %). Pero el encadenado cae de +531 % a +208 % y el Calmar empeora en 4 de 6 años.
2. **2021 es el caso adverso:** se apagó el 20 de mayo (después del desplome), luego 10 apagados y 10 encendidos; cada reinicio recompra el índice entero (216 USDT de costos solo en el índice). Caída −47 % (peor que sin filtro) y costos de 3.4 %.
3. **Quitar satélites y estables sí ayudó (V3-ref vs V2, ablación post hoc, no era criterio):** menos caída en los 6 años, costos 0.3 %-1.1 % (V2: 1.4 %-2.5 %), encadenado +531 % vs +468 %. DCA e índice dan exactamente el mismo PnL que en V2 (mismos parámetros y capital), lo que valida la comparación. El carry duplicó su aporte (2020 +512, 2021 +808, 2022 −35, 2023 +110, 2024 +257 USDT).
4. **El problema de fondo sigue:** el beta (DCA+índice) causa la caída. V3-ref cae −43 % en 2019 y −45 % en 2021.
5. Sharpe 2022 de V3 (−2.8) no es informativo: portafolio plano con volatilidad casi nula.

## 4. Reserva V2 2025-2026 (corrida única, carry de KuCoin como V1)

| Tramo | V2 ROI | caída máx. | costos | BTC ROI / caída | V1 Actual / Dinámico / Indexado |
|---|---|---|---|---|---|
| 1 ene–10 oct 2025 | +10.3 % | −18.5 % | 1.60 % | +20.5 % / −30.9 % | −10.7 / −30.0 / −3.2 % |
| 2025 completo | −4.9 % | −23.8 % | 2.11 % | −6.3 % / −34.8 % | — |
| 1 ene–10 oct 2026 | −0.7 % | −20.4 % | 1.28 % | −5.3 % / −40.3 % | −10.1 / −18.6 / −4.1 % |

- Criterios: C1 ✓, C3 ✗ en 2025 / ✓ en 2026, C4 ✓ (2/2), C6 ✓ (peor satélite −20.1 %). C5 (reportado): B − A = +56 USDT en 2025 y +35 en 2026; B gana 3 de 4 comparaciones (pequeño, pocos datos).
- V2 supera a los tres simuladores V1 en el mismo tramo; frente a BTC pierde en 2025 (+10.3 vs +20.5) y gana en 2026 (−0.7 vs −5.3), siempre con menor caída.
- Carry con funding de KuCoin casi no operó: +2 / 0 USDT (BTC), −2 / −1 (ETH), con costos de 28-32 USDT en 2025. Darle 40 % del capital (V3) implicaría capital ocioso con el funding actual.

## 5. Recomendaciones

1. Descartar el filtro SMA200 tal como está; no ajustar la ventana con estos datos.
2. Llevar V3-ref a paper trading en vivo como simulador aparte (núcleo sin filtro, sin satélites/estables), decidiendo antes el peso del carry.
3. Atacar la caída del beta con una hipótesis nueva, pre-registrada y probada solo hacia adelante.
4. Medir el funding real en vivo antes de asignar 40 % a carry.

## 6. Límites

Contaminación (pesos, umbrales y estructura salen de mirar 2019-2026); ablación V3-ref vs V2 post hoc; supervivencia, carry con datos de Binance 2020-2024, liquidez constante, sin impuestos (como V2); un solo valor del filtro (200 días); días con filtro de 2019 no calculados.
