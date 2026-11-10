# Observatorio de mercado — fases 0 a 3 · PRE-REGISTRO

Se escribe y se sube **antes** de calcular o recolectar nada. Todo cambio posterior se anota al final en "Cambios posteriores" y **no cuenta** como evidencia a favor.
Es un bot que **solo mide y registra**: no opera, no envía órdenes, no toca los simuladores. Dinero ficticio y cero llaves de API.

## 0. Honestidad previa (léase primero)

- Las etiquetas de la fase 0 ("mínimo de 12 meses", "peor semana del año"…) **no son señales de compra o venta**. Describen dónde está el precio; la pregunta es si decir
  eso ayuda a anticipar algo. La respuesta más probable para varias de ellas es "no hay evidencia suficiente", y el tablero lo dirá así.
- **Sesgo de supervivencia:** el universo se eligió hoy (Top-25 de `config_index.py`). Las monedas que murieron no están, así que los rebotes tras mínimos se ven mejor de lo que
  fueron. Por eso toda conclusión debe sostenerse también en BTC+ETH solos (que sí existían y sobrevivieron por razones menos selectivas).
- **Pocos episodios independientes:** en 7 años hay muy pocos mínimos "distintos" de BTC; las monedas caen casi todas el mismo día. Contamos **episodios de mercado**, no días ni monedas.
- **"Forecast":** no se predice el precio de mañana. Se registran probabilidades y pronósticos de volatilidad con fecha, y se miden después contra una línea base simple.
- Esto no es validación de una estrategia de trading. Es medición descriptiva con una prueba estadística estricta y un periodo de confirmación.

## 1. Estructura

| Fase | Qué mide | Fuente | Cómo se evalúa | Cuándo hay veredicto |
|---|---|---|---|---|
| **0** | Posición en el rango de 12 meses, extremos de retorno y volatilidad, amplitud de mercado | Velas diarias de Binance spot (2019 → 2026-10-31) | Backtest en frío con descubrimiento (2019-2023) y confirmación (2024-2026) | Al correr (una sola vez) |
| **1** | Flujo de órdenes y derivados (compra/venta agresiva, funding, interés abierto, liquidaciones, libro, stablecoins, volatilidad implícita) | Binance spot, OKX, KuCoin Futures, DefiLlama, Deribit (lo que el sondeo confirme) | Registro en vivo hacia adelante; correlación de rangos con retorno y volatilidad futuros | ≥ 90 días de registro |
| **2** | Anuncios y calendario: listados/retiros en exchanges, FOMC, CPI | Anuncios de exchanges, calendarios oficiales | Estudio de eventos (retorno anormal en ventanas) | ≥ 20 eventos por tipo |
| **3** | Noticias y redes (RSS de medios, Reddit si es accesible) | RSS públicos | Puntaje diario contra retorno/volatilidad futuros, controlando por Fear & Greed y retorno previo | ≥ 120 días de registro |

Todo se guarda con **marca de tiempo del momento en que se observó** (nada se reconstruye con información posterior). Los titulares y publicaciones se guardan crudos (título, fuente, enlace, hora) para poder
re-puntuar con otro método sin perder nada; el puntaje lleva la versión del método.

## 2. Fase 0 — definiciones exactas (fijas; no se agregan etiquetas después de ver resultados)

**Universo:** las 25 monedas de `config_index.TOP25` (incluyen BTC y ETH). Cada moneda entra a las etiquetas desde que tiene 365 cierres diarios.
**Datos:** cierres diarios UTC de Binance spot, hasta el 2026-10-31 inclusive (fijo, para que repetir la corrida dé lo mismo). No se descartan días ni se suavizan precios.

**Las 8 etiquetas evaluadas** (ventana = 365 días, sin contar el día evaluado):

| Id | Se activa cuando… |
|---|---|
| `min12m` | el cierre ≤ el menor cierre de los 364 días previos |
| `max12m` | el cierre ≥ el mayor cierre de los 364 días previos |
| `peor_semana` | el retorno de 7 días ≤ el menor retorno de 7 días de los 364 días previos |
| `mejor_semana` | el retorno de 7 días ≥ el mayor retorno de 7 días de los 364 días previos |
| `vol_baja` | la volatilidad realizada de 30 días está en el percentil ≤ 10 de su propia ventana de 365 días |
| `vol_alta` | ídem, percentil ≥ 90 |
| `capitulacion_amplia` | ≥ 50 % de las monedas con ventana completa tuvieron `min12m` en los últimos 7 días (etiqueta de mercado, no de moneda) |
| `euforia_amplia` | ídem con `max12m` |

**Solo descriptivas (se muestran, no se evalúan):** percentil del cierre en el rango de 365 días, distancia al mínimo y al máximo de 12 meses, caída desde el máximo histórico, días desde el último
mínimo de 12 meses, amplitud (número de monedas cerca de mínimos/máximos).

**Episodio:** para una moneda, días consecutivos con la etiqueta, o separados por menos de 30 días, forman un episodio (cuenta su primer día). **Episodio de mercado:** episodios de cualquier moneda a menos de 30 días unos de otros forman uno.
Los resultados se calculan por episodio (primer día), no por día.

**Resultado a medir:** retorno logarítmico desde el cierre del día del episodio hasta el cierre de t+h, con h ∈ {7, 30, 90} días (solo episodios con h completo dentro de los datos). Para `vol_baja`/`vol_alta`, además, la volatilidad realizada de los 30 días siguientes
frente a la actual.
**Línea base:** la mediana del mismo resultado en todos los días elegibles de esa moneda en el mismo periodo. **Exceso** = mediana de episodios − línea base (agrupado entre monedas).

**Prueba:** permutación por **desplazamiento circular** (2,000 sorteos): se desplaza la matriz completa de etiquetas (todas las monedas a la vez) un número aleatorio de días, se vuelven a formar episodios y se calcula el mismo exceso;
el valor p es la proporción de sorteos con exceso en valor absoluto ≥ al observado. Así se conserva cómo se agrupan las monedas y los episodios (sortear fechas sueltas por moneda daría p demasiado pequeños).
Se hacen 8 etiquetas × 3 horizontes = 24 pruebas, así que el umbral es **p < 0.05 / 24 ≈ 0.002** (Bonferroni).

**Una etiqueta cuenta como "con evidencia" en un horizonte solo si cumple TODO:**
1. Descubrimiento (etiquetas con fecha 2019-01-01 a 2023-12-31): ≥ 10 episodios de mercado y p < 0.002.
2. Confirmación (2024-01-01 a 2026-10-31): ≥ 4 episodios de mercado, mismo signo del exceso y p < 0.05.
3. Mismo signo del exceso en BTC+ETH solos (sin sesgo de supervivencia).
4. Al quitar el año con más episodios, el signo se mantiene.

Si falla cualquiera: **"sin evidencia suficiente"**. Si no hay episodios suficientes: **"sin veredicto (muestra pequeña)"**. Son resultados válidos y se publican igual.
Para `vol_baja`/`vol_alta` se espera persistencia (la volatilidad es la parte más predecible); se reporta como control del método y no como hallazgo.

**Qué se publica en el tablero:** por etiqueta y horizonte, el número de episodios, la mediana, el porcentaje positivo, el exceso frente a la base y el veredicto; las alertas del día con su estadística histórica al lado
(siempre con el tamaño de muestra y la leyenda "contexto, no señal de compra").

## 3. Fase 1 — flujo de órdenes y derivados (registro en vivo)

**Series candidatas** (BTC y ETH como mínimo; el resto del Top-25 donde la fuente lo permita), cada hora o cada día según la fuente:
- Compra agresiva sobre volumen total (campo `taker buy base volume` de las velas de Binance spot).
- Funding rate y su anualización; interés abierto y su cambio de 24 h; razón largos/cortos; liquidaciones de largos y cortos (OKX / KuCoin Futures; Binance Futures y Bybit están bloqueados desde GitHub Actions).
- Desbalance del libro de órdenes a ±1 % y ±5 % de profundidad (Binance, OKX).
- Oferta de stablecoins y su cambio de 7 días (DefiLlama).
- Índice de volatilidad implícita DVOL (Deribit) y prima de Coinbase frente a Binance, si el sondeo las confirma.

**Predicciones registradas cada día a las 00:00 UTC** (BTC y ETH):
- P(retorno a 7 días > 0). Modelo inicial = frecuencia base de los últimos 365 días. Cualquier modelo posterior debe superarla en **Brier skill score** con ≥ 90 predicciones ya realizadas.
- Pronóstico de volatilidad realizada a 7 días. Línea base = volatilidad realizada de 30 días. Candidatos: EWMA y GARCH(1,1), con DVOL si existe; se miden con MAE y QLIKE contra la línea base.

**Evaluación (no antes de 90 días de datos):** correlación de rangos (Spearman) de cada variable contra retorno y volatilidad futuros a 7 días. Una variable "aporta" solo si |ρ| ≥ 0.15 con n ≥ 120,
mismo signo en las dos mitades del periodo, y mejora el pronóstico de volatilidad sobre la línea base. En caso contrario, "sin evidencia suficiente".

## 4. Fase 2 — anuncios y calendario

- **Eventos:** nuevos listados y retiros en Binance/OKX/KuCoin (anuncios públicos), reuniones FOMC y publicación de CPI de EE. UU. (calendarios oficiales). Cada evento se guarda con la hora de publicación.
- **Medición:** retorno anormal (frente a la mediana de la misma moneda en días sin evento) en [−1, +1] y [+1, +7] días. Con p < 0.01 por tipo de evento, ≥ 20 eventos por tipo y mismo signo en las dos mitades. Menos de 20 eventos: "sin veredicto".
- Para listados: solo se mide la moneda listada, con la salvedad de que el anuncio suele llegar después de rumores y de que los listados recientes son pocos.

## 5. Fase 3 — noticias y redes

- **Fuentes:** RSS de medios cripto; Reddit (RSS) solo si es accesible; GDELT si el sondeo lo permite. X/Twitter y los grupos privados de Telegram quedan fuera (API de pago o sin acceso legítimo). No hay raspado de sitios que lo prohíban.
- **Puntaje:** por defecto determinista y sin costo (léxico de tono con términos cripto; versión fija y registrada). Un modelo de lenguaje puede puntuar los mismos titulares como segunda columna **solo con una llave guardada como secreto**;
  nunca reemplaza al puntaje base ni se mezcla con él.
- **Agregación diaria:** tono medio, número de menciones y dispersión (global y por moneda cuando el titular nombra una).
- **Evaluación (no antes de 120 días):** correlación de rangos del tono del día con el retorno y la volatilidad de los 7 días siguientes, controlando por el retorno de los 7 días previos y por el Fear & Greed
  (la pregunta es si aporta algo que esos dos no dicen). Criterio: |ρ parcial| ≥ 0.15, n ≥ 120, mismo signo en las dos mitades. Si no, "sin evidencia suficiente".
- **Límites conocidos:** el precio suele moverse antes de que una noticia se puntúe; hay promoción pagada y bots; el léxico no entiende ironía ni contexto. Se reporta el número de titulares por día para saber cuándo el dato es flaco.

## 6. Reglas de juego

1. Las 8 etiquetas, sus definiciones, los horizontes y los criterios no cambian después de ver resultados. Una etiqueta nueva exige un nuevo pre-registro y empieza otra vez en descubrimiento/confirmación con datos que no haya visto.
2. Un resultado "sin evidencia" no se rescata cambiando parámetros. Se publica tal cual.
3. Solape: la fase 0 como señal de entrada se parecería a los bots de tendencia (`max12m`) y de reversión (`min12m`). Por eso su uso permitido es **contexto y propuesta de filtro de riesgo**
   (reducir tamaño o pausar el carry en extremos); ningún simulador en vivo cambia por esto sin un pre-registro aparte.
4. Cualquier "predicción" mostrada en el tablero lleva su historial de aciertos y la leyenda: estimación estadística, no garantía.
5. El observatorio falla por separado: si una fuente no responde, esa serie queda vacía ese día y se registra el hueco (no se interpola ni se inventa).

## 7. Cronograma

- Fase 0: corre una vez en cuanto el código y sus pruebas estén listos; resultados en la rama `mercado-fase0`. Luego el tablero calcula las alertas del día con esos mismos números fijos.
- Fase 1: empieza a registrar cuando el sondeo confirme las fuentes; veredicto a los 90 días.
- Fases 2 y 3: empiezan a registrar junto con la fase 1; veredicto a los 90–120 días.

## Cambios posteriores

- **2026-11-10 · aclaraciones ANTES de calcular cualquier resultado real** (solo se había probado el código con datos inventados): (a) la prueba de permutación pasó de "fechas al azar por moneda" a desplazamiento circular, por la razón de arriba;
  (b) las etiquetas de mercado (`capitulacion_amplia`, `euforia_amplia`) exigen al menos 8 monedas con ventana completa ese día, y se evalúan con el resultado de todas las monedas elegibles agrupado, con la fecha de la etiqueta compartida;
  (c) el percentil de volatilidad se mide contra los 365 valores previos (estricto: fracción de valores previos menores que el de hoy). Ninguna de las tres cambia las hipótesis ni los umbrales.
- **2026-11-10 · resultado de la fase 0 y aclaraciones para las fases 1-3** (la fase 0 ya corrió; las fases 1-3 todavía no tienen ni un día de datos):
  (a) **Fase 0: 0 de 24 combinaciones con evidencia** (ver rama `mercado-fase0`). Ningún criterio se movió después de ver esto. "Peor semana del año → 7 días" quedó con p = 0.008 en descubrimiento (umbral 0.0021) y 0.063 en confirmación: es una pista a vigilar en vivo con la misma regla, no un hallazgo.
  (b) El control de volatilidad de la fase 0 mide cuánto cambia la volatilidad futura frente a la actual (reversión a la media), no persistencia pura; se reporta tal cual y no cuenta como criterio.
  (c) **Fuentes verificadas con `scripts/probe_market.py` desde GitHub Actions:** responden Binance spot, OKX (interés abierto, largos/cortos, compra agresiva, liquidaciones, funding, libro), KuCoin Futures, Deribit (DVOL), Coinbase, DefiLlama, CoinGecko, anuncios de Binance/OKX/KuCoin, página de la Fed, 6 RSS de medios cripto, Reddit por RSS y Stocktwits.
  No responden: BLS (CPI), CryptoPanic, Bluesky, Reddit en JSON, GDELT (límite de 1 petición cada 5 s), Coinbase blog. **CPI queda fuera** de la fase 2 y GDELT de la fase 3. El libro de órdenes se mide solo en los primeros 100 niveles (franja de precio angosta; contexto, no señal).
  (d) **FOMC:** el estudio de eventos usa las 40 decisiones de 2022 a 2026 según los calendarios publicados por la Fed (para poder evaluarlo sin esperar años); listados y retiros solo cuentan desde que el observatorio los guarda más los que devuelven las páginas de anuncios (pocos).
  (e) **Evaluación de fases 1 y 3:** las ventanas de 7 días se traslapan día a día; se informa el n efectivo (≈ n/7) y se mantiene el mínimo de 120 días como regla. Las fotos se toman cada hora; para evaluar se usa la primera del día (≈00:07 UTC) y los objetivos se miden desde el cierre de la víspera. En noticias el día es el de OBSERVACIÓN, no el que declara el feed.
  (d bis) La primera corrida real leyó de la página de la Fed fechas que no son reuniones (p. ej. el discurso de Jackson Hole, 2025-08-22) y años fuera del rango; se corrigió para tomar de la página solo reuniones de 2027 en adelante y se limpió el estado guardado. Binance devolvió HTTP 400 con 30 anuncios por página: se usa la página de 5 (la probada). Reddit limitó las peticiones (429): se espacian 8 s entre subreddits y se dejaron 3.
  (d ter) La prima de Coinbase de las primeras fotos se calculó contra el cierre de la vela de 1 h ya cerrada (hasta 60 min de antigüedad), lo que mete ruido de precio; desde 2026-11-10 se calcula contra el precio en vivo de Binance. Son 3 fotos de ~120 requeridas; no cambia ningún criterio. La página suma un "Panorama" gráfico: la probabilidad de subida/bajada mostrada es solo la frecuencia base y las lecturas de indicadores (umbrales fijos "de cara") no la modifican hasta que una variable cumpla el criterio de la fase correspondiente.
  (f) Puntaje de noticias: léxico `lex-v1` (determinista). El puntaje con modelo de lenguaje no se activa en esta versión (requiere un secreto de API) y, cuando se active, será una columna aparte.
