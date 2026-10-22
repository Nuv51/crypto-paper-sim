# Simulador en frío 2019-2024 V2 — Reestructurado low cost · RESULTADOS

Pre-registro: `BACKTEST_V2_2019_2024.md` (criterios fijados antes de correr). Código de las corridas: commit `b80d3cc` (segunda corrida; la primera falló en 2021 por huecos de datos y se anotó en el pre-registro). Tablas completas en la rama `backtest-v2`; scripts de análisis en `backtest_v2/analysis/`. Dinero ficticio; cifras sobre los 10,000 USDT completos (el efectivo no asignado cuenta).

## 1. Veredicto contra los criterios

| # | Criterio | Resultado | |
|---|---|---|---|
| C1 | Caída máx. ≤ 40 % cada año | −43.9 % (2019), −45.0 % (2021); los otros cuatro entre −16.8 % y −33.8 % | ✗ |
| C2 | ROI > 0 en ≥ 4 de 6 años | 5 de 6 (solo 2022 negativo) | ✓ |
| C3 | Comisiones + deslizamiento < 1.5 % del capital por año | 2.3 % a 4.8 % (solo comisiones: 1.05 % a 1.85 %; superan 1.5 % en 2019-2021) | ✗ |
| C4 | Caída máx. menor que la de BTC en ≥ 5 de 6 años | 6 de 6 | ✓ |
| C5 | El interruptor aporta (B − A > 0 y B gana ≥ 8 de 12) | suma B − A = +23 USDT, B gana 4, empata 2, pierde 6 | ✗ |
| C6 | Ningún satélite pierde > 25 % de su capital | peor caso −21.8 % | ✓ |

H1 (núcleo low cost) se cumple a medias: gana 5 de 6 años y cae menos que BTC, pero no cumple el tope de caída ni el de costos. H2 (interruptor) no se sostiene. H3 (límites duros) se cumple.

## 2. Por año (10,000 USDT al 1 de enero)

| Año | ROI V2 | Caída máx. V2 | Sharpe V2 | ROI BTC | Caída máx. BTC | Sharpe BTC | ROI ETH | Índice igual peso (sin costos) |
|---|---|---|---|---|---|---|---|---|
| 2019 | +1.9 % | −43.9 % | 0.22 | +94.4 % | −53.2 % | 1.27 | −1.7 % | −1.9 % |
| 2020 | +128.3 % | −32.9 % | 2.16 | +302.0 % | −60.5 % | 2.25 | +470.2 % | +150.1 % |
| 2021 | +88.8 % | −45.0 % | 1.37 | +59.8 % | −54.7 % | 0.97 | +399.2 % | +356.8 % |
| 2022 | −31.9 % | −33.8 % | −1.46 | −64.2 % | −67.4 % | −1.34 | −67.5 % | −74.8 % |
| 2023 | +42.5 % | −16.8 % | 1.67 | +155.6 % | −21.7 % | 2.34 | +90.8 % | +111.2 % |
| 2024 | +33.4 % | −23.1 % | 1.12 | +121.3 % | −32.3 % | 1.68 | +46.3 % | +62.9 % |

Encadenado 2019-2024: V2 +468 % vs BTC +2,428 %. V2 superó a BTC en ROI en 2021 y 2022 (en 2022 perdió la mitad: −32 vs −64) pero solo en 2021 superó su Sharpe.

## 3. De dónde sale el resultado (PnL en USDT)

| Bot | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 |
|---|---|---|---|---|---|---|
| v01 DCA | 86 | 5,039 | 1,053 | −907 | 962 | 705 |
| v02 carry BTC | — | 131 | 229 | 0 | 33 | 71 |
| v03 carry ETH | — | 125 | 176 | −17 | 22 | 58 |
| v04 estables | 13 | 6 | 8 | 0 | — | 2 |
| v05 índice Top-25 | 309 | 7,455 | 7,182 | −2,029 | 3,351 | 2,691 |
| 4 satélites (suma) | −223 | 76 | 228 | −238 | −120 | −190 |

- **El núcleo es beta.** Índice + DCA explican casi todo el PnL (y casi toda la caída: el índice llegó a −62 % a −70 % de caída propia en 2019-2022). El carry y las estables aportan estabilidad, no volumen.
- **Los satélites perdieron en 4 de 6 años** (suma −467 sobre 2,000 de capital). Antes de costos suman +321; los costos suman 788. Es la misma lección que V1: el costo se come lo que la señal produce.
- **Costos:** 234 a 480 USDT por año. Lo más caro por capital: el carry (≈ 100-146 USDT por año sobre 1,250 y 750 de capital) y los satélites (86-161 por año sobre 2,000). En 2019 las estables gastaron 88 para ganar 13.
- **Carry BTC en 2022:** 0 operaciones (el funding no cumplió el umbral de entrada), el capital estuvo ocioso.

## 4. El interruptor de volatilidad

La volatilidad de BTC a 14 días estuvo por encima de 40 % el **75 % de los días** (48 % en 2023, 99 % en 2021). Con ese umbral el interruptor casi siempre está encendido: en 2021 los gemelos fueron idénticos. Las diferencias B − A (grid: +56, −27, 0, −46, +80, −34; tendencia: −3, −94, 0, +30, +69, −7) cambian de signo sin patrón: es ruido. Cambiar el umbral con estos datos sería ajustar a la muestra; no se hizo.

## 5. Límites duros (H3)

Funcionaron: ninguna pérdida de satélite pasó de −21.8 %. La tendencia se retiró por el tope de pérdida en 2019, 2023 y 2024 (con ~−20 %) y el presupuesto de rotación pausó a los satélites con frecuencia (4× el capital agotado en pocos días en enero de 2021). Es protección, no rentabilidad.

## 6. Orientación estadística (no es prueba)

72 meses: 40 positivos, media +3.0 % mensual, peor mes −14.9 %, mejor +36.7 %. Remuestreando años de 12 meses de esos 72: percentil 5 = −27 %, mediana +33 %, percentil 95 = +150 %, probabilidad de año negativo ≈ 22 %. Todo depende de 2020-2021.

## 7. Sesgos que importan

- **Supervivencia:** en 2024 quedaron fuera por no cotizar todo el año MATIC (cambió a POL) y XMR (deslistada), que habrían estado dentro del Top-25 (corte 2.89 B USD); el efecto sobre el índice es de segundo orden pero existe. En 2019-2021 no hubo excluidas de este tipo.
- **Universo 2019 de 15 monedas;** sin carry en 2019 y sin estables en 2023 (capital ocioso cuenta en el ROI).
- **Carry con datos de Binance** (comisión y funding distintos a KuCoin).
- **Costos de deslizamiento por nivel de liquidez actual,** no la real de 2019-2020.
- **Contaminación:** conocemos la historia; V2 se diseñó tras ver 2025-2026.

## 8. Lectura

1. La estructura *low cost* sí ganó dinero en 5 de 6 años con un ciclo completo, pero eso es mayormente beta de cripto con algo de amortiguación; no mejoró el Sharpe de BTC salvo en 2021.
2. Los dos activos que añadían "edge" (satélites, interruptor) no lo demostraron: pierden en neto y el interruptor no discrimina con ese umbral.
3. Lo que sí agrega valor demostrable es la **gestión de riesgo** (topes duros) y la **disciplina de medición** (pre-registro, gemelos, criterios numéricos).
4. Para el siguiente paso, la prueba limpia es el **paper trading en vivo** (desde 2026-10-16), no más backtests sobre estos años. Cualquier variante nueva (menos peso en índice, filtro de tendencia sobre el núcleo, menos rotación del carry) se pre-registra antes y se prueba solo hacia adelante.
