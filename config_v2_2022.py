"""Simulador V2 · Reestructurado low cost — BACKTEST EN FRÍO 2022 (generado por scripts/make_config_v2.py; no editar a mano).

Universo y monedas decididos con la información del 2022-01-01 (foto de CoinMarketCap del 2021-12-26; Binance spot) según
BACKTEST_V2_2019_2024.md. Parámetros de cada bot = los de V1 salvo los cambios declarados allí.
"""

PORTFOLIO_CAPITAL = 10_000.0      # USDT FICTICIOS
INTERVAL = "1h"
PORTFOLIO_RISK = dict(max_drawdown=None, cooldown_bars=168)

# Capitalización de la foto (USD), de mayor a menor: Top-25 de las monedas elegibles (79 elegibles).
CAPS_USD = {
    "BTCUSDT": 960.9000e9,
    "ETHUSDT": 483.6202e9,
    "BNBUSDT": 91.2394e9,
    "SOLUSDT": 61.1702e9,
    "ADAUSDT": 48.7359e9,
    "XRPUSDT": 43.7892e9,
    "DOTUSDT": 30.9437e9,
    "AVAXUSDT": 28.0245e9,
    "DOGEUSDT": 25.2101e9,
    "SHIBUSDT": 21.0363e9,
    "MATICUSDT": 20.4119e9,
    "UNIUSDT": 11.7456e9,
    "LTCUSDT": 10.8068e9,
    "LINKUSDT": 10.7458e9,
    "ALGOUSDT": 10.2170e9,
    "NEARUSDT": 9.7244e9,
    "BCHUSDT": 8.5643e9,
    "TRXUSDT": 8.3096e9,
    "ATOMUSDT": 7.2854e9,
    "XLMUSDT": 7.2067e9,
    "MANAUSDT": 7.0505e9,
    "AXSUSDT": 6.5517e9,
    "SANDUSDT": 6.1872e9,
    "VETUSDT": 6.0795e9,
    "FTMUSDT": 5.9629e9,
}
SLIPPAGE_BPS = {
    "BTCUSDT": 5,
    "ETHUSDT": 5,
    "BNBUSDT": 5,
    "SOLUSDT": 5,
    "ADAUSDT": 5,
    "XRPUSDT": 5,
    "DOTUSDT": 5,
    "AVAXUSDT": 5,
    "DOGEUSDT": 5,
    "SHIBUSDT": 5,
    "MATICUSDT": 5,
    "UNIUSDT": 8,
    "LTCUSDT": 5,
    "LINKUSDT": 5,
    "ALGOUSDT": 8,
    "NEARUSDT": 5,
    "BCHUSDT": 8,
    "TRXUSDT": 5,
    "ATOMUSDT": 5,
    "XLMUSDT": 8,
    "MANAUSDT": 5,
    "AXSUSDT": 8,
    "SANDUSDT": 5,
    "VETUSDT": 8,
    "FTMUSDT": 5,
}
INDEX_SYMBOLS = list(CAPS_USD)

BOTS = [
    dict(
        id="v01_dca", kind="dca", name="DCA BTC+ETH", exchange="bitso", symbols=["BTCUSDT", "ETHUSDT"],
        capital_pct=0.20, risk_level="bajo", vol_profile="Majors (volatilidad baja-media)", slippage_bps=2,
        differentiator="Núcleo: compra semanal de monto fijo, sin señales ni stop (acumulación, no 'edge'). Igual a V1 b03.",
        params=dict(interval_hours=168, contribution_pct=0.03), risk=dict(max_drawdown=0.45, action="flag_only"),
    ),
    dict(
        id="v02_carry_btc", kind="carry", name="Carry BTC spot-perpetuo", exchange="kucoin", symbols=["BTCUSDT", "BTCUSDT~PERP"],
        capital_pct=0.125, risk_level="bajo", vol_profile="Majors · market-neutral (cobra funding, no apuesta a dirección)", slippage_bps=2,
        differentiator="Núcleo: largo spot + corto perpetuo. Mismos parámetros que el carry BTC del simulador actual (V1).",
        params=dict(perp_taker=0.0006, perp_slip_bps=2.0, leverage=2.0, avg_n=3, min_apr=0.05, min_hold_days=10, neg_periods_exit=3, margin_stress=0.8),
        risk=dict(max_drawdown=0.05, action="pause_and_resume", cooldown_bars=168, max_strikes=3, strike_window_bars=720),
    ),
    dict(
        id="v03_carry_eth", kind="carry", name="Carry ETH spot-perpetuo", exchange="kucoin", symbols=["ETHUSDT", "ETHUSDT~PERP"],
        capital_pct=0.075, risk_level="bajo", vol_profile="Majors · market-neutral (cobra funding, no apuesta a dirección)", slippage_bps=2,
        differentiator="Núcleo: carry sobre ETH con el umbral relajado del dinámico (V1, d02).",
        params=dict(perp_taker=0.0006, perp_slip_bps=2.0, leverage=2.0, avg_n=3, min_apr=0.03, min_hold_days=20, neg_periods_exit=3, margin_stress=0.8),
        risk=dict(max_drawdown=0.05, action="pause_and_resume", cooldown_bars=672, max_strikes=3, strike_window_bars=2880),
    ),
    dict(
        id="v04_stable", kind="stable", name="Stablecoins · peg", exchange="binance", symbols=["BUSDUSDT"],
        capital_pct=0.10, risk_level="bajo", vol_profile="Stablecoins (volatilidad mínima; riesgo de cola = de-peg)", slippage_bps=1,
        differentiator="Núcleo: compra desvíos del peg y vende al volver. Igual a V1 b02 (umbral 0.30 %); solo cambian las monedas disponibles cada año.",
        params=dict(entry_dev=0.003, exit_dev=0.0005, stop_pct=0.01, guard_dev=0.015, depeg=0.02, depeg_bars=6, max_hold_bars=72),
        risk=dict(max_drawdown=0.02, action="pause_and_resume", cooldown_bars=168, max_strikes=3, strike_window_bars=720),
    ),
    dict(
        id="v05_index_cap25", kind="index", name="Índice Top-25 (capitalización) · rebalanceo trimestral", exchange="binance",
        symbols=INDEX_SYMBOLS, caps_usd=dict(CAPS_USD), slippage_map_bps=dict(SLIPPAGE_BPS), slippage_bps=10,
        capital_pct=0.30, risk_level="medio", vol_profile="Mercado amplio: domina BTC/ETH (tope 30 % cada una)",
        differentiator="Núcleo: Top-25 por capitalización con tope de 30 %, rebalanceo cada 90 días (V1 usaba 30).",
        params=dict(weighting="cap", cap_max=0.30, rebalance_hours=2160, cash_buffer=0.005, min_trade_usdt=8.0, min_weight=0.0008),
        risk=dict(max_drawdown=0.50, action="flag_only"),
    ),
    dict(
        id="v06_grid_eth", kind="grid", name="Grid ETH · siempre activo", exchange="binance", symbols=["ETHUSDT"],
        capital_pct=0.05, risk_level="medio", vol_profile="Volatilidad acotada / en consolidación", slippage_bps=3,
        differentiator="Satélite A: grid ETH de V1 (±10 %, 16 niveles), sin interruptor. Gemelo del v07.",
        params=dict(range_pct=0.1, n_levels=16, capital_use=0.95, stop_buffer=0.02, recenter_wait_bars=72),
        risk=dict(max_drawdown=0.1, action="pause_and_resume", cooldown_bars=168, max_strikes=3, strike_window_bars=720, max_loss_initial=0.20, max_turnover_month=4.0),
    ),
    dict(
        id="v07_grid_eth_gate", kind="grid", name="Grid ETH · interruptor de volatilidad", exchange="binance", symbols=["ETHUSDT"],
        capital_pct=0.05, risk_level="medio", vol_profile="Volatilidad acotada / en consolidación", slippage_bps=3,
        differentiator="Satélite B: el mismo grid, activo solo cuando la volatilidad de BTC a 14 días supera 40 % (hipótesis a probar).",
        params=dict(range_pct=0.1, n_levels=16, capital_use=0.95, stop_buffer=0.02, recenter_wait_bars=72),
        risk=dict(max_drawdown=0.1, action="pause_and_resume", cooldown_bars=168, max_strikes=3, strike_window_bars=720, max_loss_initial=0.20, max_turnover_month=4.0), gate=dict(type="btc_vol", symbol="BTCUSDT", lookback_days=14, threshold=0.40),
    ),
    dict(
        id="v08_trend", kind="trend", name="Tendencia · siempre activo", exchange="binance", symbols=["SOLUSDT", "ADAUSDT"],
        capital_pct=0.05, risk_level="alto", vol_profile="Altcoins de volatilidad inestable/alta", slippage_bps=6,
        differentiator="Satélite A: tendencia/momentum de V1 sobre las 2 mayores monedas elegibles (sin BTC, ETH ni BNB), sin interruptor.",
        params=dict(fast=24, slow=96, roc_n=72, stop_pct=0.04, trail_start=0.05, trail_margin=0.025),
        risk=dict(max_drawdown=0.15, action="pause_and_resume", cooldown_bars=168, max_strikes=3, strike_window_bars=720, max_loss_initial=0.20, max_turnover_month=4.0),
    ),
    dict(
        id="v09_trend_gate", kind="trend", name="Tendencia · interruptor de volatilidad", exchange="binance", symbols=["SOLUSDT", "ADAUSDT"],
        capital_pct=0.05, risk_level="alto", vol_profile="Altcoins de volatilidad inestable/alta", slippage_bps=6,
        differentiator="Satélite B: la misma tendencia, activa solo cuando la volatilidad de BTC a 14 días supera 40 % (hipótesis a probar).",
        params=dict(fast=24, slow=96, roc_n=72, stop_pct=0.04, trail_start=0.05, trail_margin=0.025),
        risk=dict(max_drawdown=0.15, action="pause_and_resume", cooldown_bars=168, max_strikes=3, strike_window_bars=720, max_loss_initial=0.20, max_turnover_month=4.0), gate=dict(type="btc_vol", symbol="BTCUSDT", lookback_days=14, threshold=0.40),
    ),
]
