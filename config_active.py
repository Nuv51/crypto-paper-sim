"""Simulador DINÁMICO: misma idea que `config.py`, pero con más movimiento para compararlos lado a lado.

Se corre aparte (carpeta `activo/` del sitio, su propio estado) con el mismo capital ficticio (10,000 USDT, 100% desplegado)
y los mismos datos de mercado reales que el simulador actual. Tres palancas, definidas de una vez y SIN afinarse a mitad de la
prueba (si se ajustaran mientras corre, la comparación dejaría de ser justa):

  1. Más activos     : más monedas por bot y algunos bots repetidos en otra moneda (grid BTC/SOL, MM ETH, carry ETH).
  2. Umbrales sueltos: entradas más fáciles (RSI 35, breakout de 24 barras, ML con P ≥ 0.55, desvío del peg 0.20 %…).
  3. Velas de 15 min : los indicadores usan el MISMO número de barras que el simulador actual, así que reaccionan ~4× más rápido.

Ojo con las unidades de tiempo: con velas de 15 min, 1 día = 96 barras. Todo lo que el simulador actual expresa en barras de
1 h pero que significa "tiempo" (pausa tras romper el límite de riesgo, ventana de rupturas, frenos globales) se re-expresa
aquí para que dure lo mismo en tiempo real: 7 días = 672 barras, 30 días = 2,880 barras.

Más operaciones NO significa más ganancia: cada ida y vuelta paga ~0.2 % de comisión + slippage. Esta simulación existe para
medir si el movimiento extra compensa sus costos, no para suponer que sí.
"""

PORTFOLIO_CAPITAL = 10_000.0   # USDT FICTICIOS, igual que el simulador actual
INTERVAL = "15m"

BARS_DAY = 96                  # barras de 15 min por día
COOLDOWN = 7 * BARS_DAY        # 672 barras = 7 días de pausa (igual que el actual)
STRIKE_WINDOW = 30 * BARS_DAY  # 2,880 barras = 30 días

# Freno global: -10 % desde el máximo del portafolio → liquida todo, pausa 7 días y reanuda solo (igual que el actual).
PORTFOLIO_RISK = dict(max_drawdown=0.10, cooldown_bars=COOLDOWN)


def _risk(max_dd: float) -> dict:
    return dict(max_drawdown=max_dd, action="pause_and_resume", cooldown_bars=COOLDOWN, max_strikes=3,
                strike_window_bars=STRIKE_WINDOW)


BOTS = [
    dict(
        id="d01_carry_btc", kind="carry", name="Carry BTC spot-perpetuo", exchange="kucoin",
        symbols=["BTCUSDT", "BTCUSDT~PERP"], capital_pct=0.10, risk_level="bajo",
        vol_profile="Majors · market-neutral (cobra funding, no apuesta a dirección)", slippage_bps=2,
        differentiator="Como el carry del simulador actual pero exige que el funding recupere sus costos en 20 días (no 10): el umbral baja de ~14.6 % a ~7.3 % anual y entra con más facilidad.",
        params=dict(perp_taker=0.0006, perp_slip_bps=2.0, leverage=2.0, avg_n=3, min_apr=0.03,
                    min_hold_days=20, neg_periods_exit=3, margin_stress=0.8),
        risk=_risk(0.05),
    ),
    dict(
        id="d02_carry_eth", kind="carry", name="Carry ETH spot-perpetuo", exchange="kucoin",
        symbols=["ETHUSDT", "ETHUSDT~PERP"], capital_pct=0.06, risk_level="bajo",
        vol_profile="Majors · market-neutral (cobra funding, no apuesta a dirección)", slippage_bps=2,
        differentiator="Segundo carry, sobre ETH, con el mismo umbral relajado (costos recuperados en 20 días): otra fuente de funding (no siempre se mueve igual que el de BTC).",
        params=dict(perp_taker=0.0006, perp_slip_bps=2.0, leverage=2.0, avg_n=3, min_apr=0.03,
                    min_hold_days=20, neg_periods_exit=3, margin_stress=0.8),
        risk=_risk(0.05),
    ),
    dict(
        id="d03_stable", kind="stable", name="Stablecoins · peg", exchange="binance",
        symbols=["USDCUSDT", "FDUSDUSDT"], capital_pct=0.08, risk_level="bajo",
        vol_profile="Stablecoins (volatilidad mínima; riesgo de cola = de-peg)", slippage_bps=1,
        differentiator="Umbral de entrada 0.20 % (en el actual, 0.30 %). Experimento: con ~0.2 % de comisión ida y vuelta se espera que gane poco o pierda.",
        params=dict(entry_dev=0.0020, exit_dev=0.0005, stop_pct=0.010, guard_dev=0.015, depeg=0.020,
                    depeg_bars=6, max_hold_bars=72),
        risk=_risk(0.02),
    ),
    dict(
        id="d04_dca", kind="dca", name="DCA Majors+", exchange="bitso",
        symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"], capital_pct=0.08, risk_level="bajo",
        vol_profile="Majors (volatilidad baja-media)", slippage_bps=2,
        differentiator="Compra cada 48 h (3.5 % del capital del bot repartido en 3 monedas), en vez de cada 7 días en 2: ~3.5× más frecuente. Cada compra debe superar el mínimo de orden (5 USDT). Sigue siendo acumulación, no 'edge'.",
        params=dict(interval_hours=48, contribution_pct=0.035),
        risk=dict(max_drawdown=0.45, action="flag_only"),
    ),
    dict(
        id="d05_grid_eth", kind="grid", name="Grid ETH", exchange="binance",
        symbols=["ETHUSDT"], capital_pct=0.08, risk_level="medio",
        vol_profile="Volatilidad acotada / en consolidación", slippage_bps=3,
        differentiator="Grid más estrecho (±6 %, 20 niveles ≈ 0.6 % por escalón) para ciclar más seguido que el actual (±10 %, 16 niveles).",
        params=dict(range_pct=0.06, n_levels=20, capital_use=0.95, stop_buffer=0.02, recenter_wait_bars=24),
        risk=_risk(0.10),
    ),
    dict(
        id="d06_grid_btc", kind="grid", name="Grid BTC", exchange="binance",
        symbols=["BTCUSDT"], capital_pct=0.06, risk_level="medio",
        vol_profile="Majors en consolidación", slippage_bps=3,
        differentiator="Mismo mecanismo que el grid ETH pero sobre BTC (menos volátil: rango algo más estrecho).",
        params=dict(range_pct=0.05, n_levels=20, capital_use=0.95, stop_buffer=0.02, recenter_wait_bars=24),
        risk=_risk(0.10),
    ),
    dict(
        id="d07_grid_sol", kind="grid", name="Grid SOL", exchange="binance",
        symbols=["SOLUSDT"], capital_pct=0.05, risk_level="alto",
        vol_profile="Altcoin de volatilidad mayor", slippage_bps=4,
        differentiator="Grid sobre SOL con rango más ancho (±9 %) por su mayor volatilidad; más ciclos pero también más riesgo de salirse del rango.",
        params=dict(range_pct=0.09, n_levels=20, capital_use=0.95, stop_buffer=0.02, recenter_wait_bars=24),
        risk=_risk(0.12),
    ),
    dict(
        id="d08_meanrev", kind="meanrev", name="Reversión a la media", exchange="kucoin",
        symbols=["BNBUSDT", "ADAUSDT", "DOTUSDT", "LTCUSDT", "ATOMUSDT", "XLMUSDT"], capital_pct=0.09, risk_level="medio",
        vol_profile="Altcoins de volatilidad estable/predecible", slippage_bps=5,
        differentiator="6 monedas (el actual, 2), RSI < 35 (el actual, 30), take-profit 3 % y hasta 4 posiciones a la vez.",
        params=dict(rsi_buy=35, tp_pct=0.03, stop_min=0.02, stop_max=0.03, max_positions=4),
        risk=_risk(0.10),
    ),
    dict(
        id="d09_mm_btc", kind="mm", name="Market making BTC", exchange="binance",
        symbols=["BTCUSDT"], capital_pct=0.05, risk_level="medio",
        vol_profile="Majors líquidos (spread estrecho)", slippage_bps=1,
        differentiator="Spread de cotización más angosto (±0.10 % en vez de ±0.15 %) y re-cotiza cada 15 min. Sigue siendo una aproximación: no valida un market maker real.",
        params=dict(half_spread=0.0010, quote_frac=0.10, target_inv=0.50, quote_stop_dev=0.20,
                    rebalance_dev=0.30, vol_guard=0.012),
        risk=_risk(0.12),
    ),
    dict(
        id="d10_mm_eth", kind="mm", name="Market making ETH", exchange="binance",
        symbols=["ETHUSDT"], capital_pct=0.04, risk_level="medio",
        vol_profile="Majors líquidos", slippage_bps=2,
        differentiator="Mismo mecanismo que el MM de BTC sobre ETH (más volátil: un poco más de spread).",
        params=dict(half_spread=0.0012, quote_frac=0.10, target_inv=0.50, quote_stop_dev=0.20,
                    rebalance_dev=0.30, vol_guard=0.014),
        risk=_risk(0.12),
    ),
    dict(
        id="d11_trend", kind="trend", name="Tendencia / Momentum", exchange="binance",
        symbols=["SOLUSDT", "AVAXUSDT", "NEARUSDT", "SUIUSDT"], capital_pct=0.08, risk_level="alto",
        vol_profile="Altcoins de volatilidad inestable/alta", slippage_bps=6,
        differentiator="EMAs más rápidas (12/48 barras en vez de 24/96) y 4 monedas (el actual, 2). Con velas de 15 min detecta tendencias de horas, no de días.",
        params=dict(fast=12, slow=48, roc_n=36, stop_pct=0.04, trail_start=0.05, trail_margin=0.025),
        risk=_risk(0.15),
    ),
    dict(
        id="d12_breakout", kind="breakout", name="Breakout dinámico", exchange="binance",
        symbols=["DOGEUSDT", "LINKUSDT", "ARBUSDT", "OPUSDT", "APTUSDT"], capital_pct=0.08, risk_level="alto",
        vol_profile="Altcoins de alta volatilidad", slippage_bps=10,
        differentiator="Canal de 24 barras (6 h) en vez de 48, filtro de volumen 1.2× (en vez de 1.5×) y 5 monedas. Se solapa por diseño con la tendencia (#11): ambos compran fuerza.",
        params=dict(entry_n=24, exit_n=12, atr_mult=1.75, vol_mult=1.2, risk_pct=0.0075, max_pos_frac=0.5),
        risk=_risk(0.17),
    ),
    dict(
        id="d13_ml", kind="ml", name="Señales ML", exchange="binance",
        symbols=["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "BNBUSDT"], capital_pct=0.08, risk_level="alto",
        vol_profile="Majors líquidos (modelo común entrenado con las cinco monedas)", slippage_bps=5,
        differentiator="Opera con P ≥ 0.55 (el actual, 0.60), horizonte de 1 h (4 velas de 15 min) y 5 monedas. Regresión logística walk-forward; registra su acierto fuera de muestra.",
        params=dict(horizon=4, train_bars=480, retrain_bars=336, thr=0.55, stop_pct=0.03, l2=5.0),
        risk=_risk(0.12),
    ),
    dict(
        id="d14_xrp", kind="xrp_rail", name="Arbitraje XRP Bitso", exchange="cross",
        symbols=["XRP~RAIL"], capital_pct=0.09, risk_level="bajo",
        vol_profile="Spread entre exchanges (XRP como riel de traslado)", slippage_bps=0,
        differentiator="Umbral de spread más bajo (0.15 % en vez de 0.30 %); sigue siendo una foto del mercado por corrida (cota superior optimista).",
        params=dict(threshold=0.0015, trade_frac=0.30, slip_bps=5.0, max_imbalance=0.35, rebalance_cost=0.0005),
        risk=_risk(0.05),
    ),
]


# Los % de arriba son pesos relativos; se escalan a 100 % para desplegar los 10,000 USDT completos, igual que el actual.
_TOTAL_PCT = sum(b["capital_pct"] for b in BOTS)
for _b in BOTS:
    _b["capital_pct"] = _b["capital_pct"] / _TOTAL_PCT
