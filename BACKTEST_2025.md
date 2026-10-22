# Backtest en frío 2025 — pre-registro

Documento escrito y publicado **antes** de correr el backtest. Fija qué se mide y con qué reglas, para que el resultado no pueda
"acomodarse" después. Si algo aquí cambia, el cambio queda en el historial de git con fecha.

## Qué es (y qué no)
Reproduce el año 2025 completo con los **mismos tres simuladores que corren en vivo**, con la misma lógica, comisiones y
deslizamiento. Responde: *"¿cómo se habrían comportado estas reglas si hubiéramos empezado el 1 de enero de 2025?"*.
No demuestra rentabilidad futura. Un año es un solo régimen de mercado, y el backtest siempre es más amable que la vida real.

## Periodo y datos
- Inicio: 2025-01-01 00:00 UTC · Fin: 2026-01-01 00:00 UTC (exclusivo). Capital ficticio: 10,000 USDT por simulador (30,000 el indexado, 10,000 por bot).
- Velas cerradas de Binance spot (API pública). Carry: perpetuo y funding de KuCoin Futures (histórico real).
- Se descargan velas **anteriores** al inicio solo para calentar indicadores (información que existía ese día). La primera vela simulada es exactamente la del 2025-01-01.
- Decide al cierre de la vela, llena a la apertura de la siguiente con comisión taker y deslizamiento (igual que en vivo).

## Los tres simuladores (parámetros congelados)
| Simulador | Configuración | Velas |
|---|---|---|
| Actual | `config.py` sin cambios | 1 h |
| Dinámico | `config_active.py` sin cambios | 15 min |
| Indexado | `config_index_2025.py` (mismos bots y parámetros que `config_index.py`; solo cambian universo y capitalizaciones) | 1 h |

**Ningún parámetro se ajusta.** Ni antes ni después de ver resultados.

## Universo del indexado (punto en el tiempo)
Generado por `scripts/make_universe_2025.py` a partir de datos de antes del 2025-01-01 (entradas en `backtest_2025/inputs/`):
1. Binance spot USDT con ≥ 365 días de historial antes del 2025-01-01.
2. Con vela diaria en ≥ 360 de los 365 días de 2025 (para poder simularlo completo).
3. Sin estables, tokens de fondos, oro tokenizado ni tokens de otros exchanges (BNB se conserva).
4. Orden por capitalización del 2025-01-01: exacta (CoinMarketCap) para las monedas de su Top-20 de ese día; para el resto, **estimada** = (cap de hoy / precio de hoy) × precio del 2024-12-31.
5. Top-25 y Top-50 del resultado. Deslizamiento por liquidez de dic-2024 (mismos escalones que en vivo).

Las monedas excluidas y la razón quedan en `backtest_2025/universe_2025.json`.

## Cifras fijadas de antemano
Por simulador y por bot: ROI total del año, caída máxima (max drawdown), Sharpe (retornos horarios, sin tasa libre, anualizado), comisiones pagadas, número de operaciones.
Referencias: comprar y mantener BTC, ETH y el índice de mercado del tablero (canasta de las 10 mayores) en el mismo periodo.
Lectura principal: ROI y caída máxima de cada simulador **frente a BTC**, no el ROI aislado.

## Reglas de ejecución del experimento
- Se corre **una sola vez**. Si falla por datos faltantes o un error de código, se corrige el código (nunca parámetros) y se anota aquí qué pasó.
- Los resultados se publican tal como salen, buenos o malos.
- Corre en un flujo aparte (`backtest-2025`), con su propio estado: no detiene, ni toca, ni aparece en el "Comparar" de los simuladores en vivo.
- **Reserva (holdout):** enero–octubre de 2026 NO se corre ahora. Será la segunda validación con las mismas reglas; la tercera es el simulador en vivo.

## Sesgos que quedan (declarados)
- **Supervivencia residual:** el universo usa monedas que aún cotizan en Binance con datos completos de 2025. Quedan fuera las que dejaron de cotizar o cambiaron de símbolo durante 2025 (p. ej. FTM, que pasó a S en enero y estaba cerca del corte del Top-50; MKR → SKY). Eso favorece levemente al índice.
- **Capitalización estimada** para las monedas fuera del Top-20: sobrestima las que liberaron mucho suministro desde entonces; puede mover el orden en el límite 25–50 y los pesos de la cola.
- **Elección de monedas de los bots activos** (`config.py`, `config_active.py`): se escogieron mirando el mercado de 2026, así que hay contaminación leve (las monedas elegidas son sobrevivientes con liquidez).
- **Deslizamiento en caídas bruscas** optimista (velas, no libro de órdenes).
- **Bot de arbitraje XRP:** no hay historial de libros de órdenes, así que no se puede medir; queda sin operar y se marca como no evaluable.
- **Carry:** depende del histórico de funding de KuCoin Futures.
- **Un solo año, un solo régimen:** el resultado describe 2025, no una expectativa.

---
## Registro de la corrida (agregado después de ejecutar)
- Corrida única del flujo `backtest-2025` (run 39719015153, código 05ba936): terminó sin fallos técnicos ni reintentos; los tres simuladores empezaron en 2025-01-01 00:00 y terminaron en la última vela de 2025 (8,760 velas de 1 h; 35,039 de 15 min).
- Resultados completos en la rama `backtest-2025` (`informe.md`, `summary.json` y `dashboard.json` por simulador). No se cambió ningún parámetro.
- Referencias del periodo: BTC −6.33 % · ETH −10.97 % · mercado (canasta de las 10 mayores) −9.18 %.
- Resultado: actual −17.09 % · dinámico −36.44 % · indexado −27.67 % (Top-25 cap −16.01 %, Top-50 cap −18.44 %, Top-25 igual peso −48.57 %).

---
## Enmienda: Reserva (holdout) 2026 — escrita ANTES de correrla
Segunda validación fuera de muestra, pedida el 2026-10-21: **2026-01-01 00:00 UTC → 2026-10-11 00:00 UTC (exclusivo; es decir, hasta el 10 de octubre inclusive)**. Se corre con las mismas reglas del pre-registro, cambiando solo lo que el cambio de fechas obliga:
- **Mismos tres simuladores y parámetros**, sin ajustes tras ver el resultado de 2025 (en el repositorio no cambió ningún parámetro de bot entre una corrida y otra; solo se agregaron archivos de backtest).
- **Universo del indexado reconstruido al 2026-01-01** (`config_index_2026.py`, generado por `scripts/make_universe_2025.py 2026`): mismas reglas (≥ 365 días de historial antes del inicio, vela diaria en el periodo, sin estables/fondos/oro/tokens de otros exchanges), ahora con ≥ 280 de los 283 días del periodo. Capitalización exacta de CoinMarketCap del 2026-01-01 para las monedas de su Top-20 y estimada para el resto con el mismo método. Entradas en `backtest_2026/inputs/`; monedas excluidas y razón en `backtest_2026/universe_2025.json` (nombre heredado).
- **Mismas cifras**: ROI, caída máxima, Sharpe, comisiones, operaciones; contra BTC, ETH y la canasta de mercado del mismo periodo.
- Flujo aparte `backtest-2026` (rama de resultados `backtest-2026`), corrida única, sin tocar los simuladores en vivo.
- Después se comparan 2025 y 2026 lado a lado. **Ninguna conclusión de esa comparación cambia parámetros**; cualquier idea nueva se probará en un periodo todavía no visto (los simuladores en vivo desde 2026-10-16).

Contaminación declarada, peor que en 2025:
- Las monedas de los bots activos (`config.py`, `config_active.py`) se escogieron en octubre de 2026 viendo el mercado de ese año; el 2026 ya no es "ciego" para esas elecciones.
- Se vieron los resultados de 2025 antes de definir esta prueba (sin retocar nada), y los primeros días de datos en vivo (desde 2026-10-16, fuera de este periodo).
- Siguen los sesgos del pre-registro (supervivencia residual, capitalización estimada, deslizamiento optimista, XRP no evaluable). Ejemplo concreto: TON (Top-30 al inicio) dejó de cotizar en Binance en junio de 2026 y queda fuera por la regla del periodo completo.
- Por eso este periodo es una **validación más débil** que un forward test real; el simulador en vivo sigue siendo la prueba limpia.
