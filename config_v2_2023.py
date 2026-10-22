"""Simulador V2 · Reestructurado low cost — BACKTEST EN FRÍO 2023 (generado por scripts/make_config_v2.py; no editar a mano).

Universo y monedas decididos con la información del 2023-01-01 (foto de CoinMarketCap del 2022-12-25; Binance spot) según
BACKTEST_V2_2019_2024.md. Parámetros de cada bot = los de V1 salvo los cambios declarados allí.
"""

PORTFOLIO_CAPITAL = 10_000.0      # USDT FICTICIOS
INTERVAL = "1h"
PORTFOLIO_RISK = dict(max_drawdown=None, cooldown_bars=168)

# Capitalización de la foto (USD), de mayor a menor: Top-25 de las monedas elegibles (85 elegibles).
CAPS_USD = {
    "BTCUSDT": 324.0932e9,
    "ETHUSDT": 149.1691e9,
    "BNBUSDT": 38.8943e9,
    "XRPUSDT": 17.4386e9,
    "DOGEUSDT": 10.0766e9,
    "ADAUSDT": 8.9458e9,
    "MATICUSDT": 6.9449e9,
    "DOTUSDT": 5.1682e9,
    "TRXUSDT": 5.0424e9,
    "LTCUSDT": 4.9766e9,
    "SHIBUSDT": 4.5515e9,
    "SOLUSDT": 4.1800e9,
    "UNIUSDT": 3.9299e9,
    "AVAXUSDT": 3.6375e9,
    "LINKUSDT": 3.0409e9,
    "XMRUSDT": 2.6467e9,
    "ATOMUSDT": 2.5832e9,
    "ETCUSDT": 2.2442e9,
    "BCHUSDT": 1.9526e9,
    "XLMUSDT": 1.9284e9,
    "APEUSDT": 1.2977e9,
    "QNTUSDT": 1.2785e9,
    "ALGOUSDT": 1.1838e9,
    "VETUSDT": 1.1717e9,
    "NEARUSDT": 1.1239e9,
}
SLIPPAGE_BPS = {
    "BTCUSDT": 5,
    "ETHUSDT": 5,
    "BNBUSDT": 8,
    "XRPUSDT": 8,
    "DOGEUSDT": 5,
    "ADAUSDT": 15,
    "MATICUSDT": 8,
    "DOTUSDT": 15,
    "TRXUSDT": 15,
    "LTCUSDT": 8,
    "SHIBUSDT": 15,
    "SOLUSDT": 8,
    "UNIUSDT": 25,
    "AVAXUSDT": 15,
    "LINKUSDT": 15,
    "XMRUSDT": 15,
    "ATOMUSDT": 15,
    "ETCUSDT": 25,
    "BCHUSDT": 25,
    "XLMUSDT": 25,
    "APEUSDT": 15,
    "QNTUSDT": 25,
    "ALGOUSDT": 25,
    "VETUSDT": 40,
    "NEARUSDT": 15,
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
        id="v04_stable", kind="stable", name="Stablecoins · peg", exchange="binance", symbols=["USDCUSDT"],
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
        id="v08_trend", kind="trend", name="Tendencia · siempre activo", exchange="binance", symbols=["XRPUSDT", "DOGEUSDT"],
        capital_pct=0.05, risk_level="alto", vol_profile="Altcoins de volatilidad inestable/alta", slippage_bps=6,
        differentiator="Satélite A: tendencia/momentum de V1 sobre las 2 mayores monedas elegibles (sin BTC, ETH ni BNB), sin interruptor.",
        params=dict(fast=24, slow=96, roc_n=72, stop_pct=0.04, trail_start=0.05, trail_margin=0.025),
        risk=dict(max_drawdown=0.15, action="pause_and_resume", cooldown_bars=168, max_strikes=3, strike_window_bars=720, max_loss_initial=0.20, max_turnover_month=4.0),
    ),
    dict(
        id="v09_trend_gate", kind="trend", name="Tendencia · interruptor de volatilidad", exchange="binance", symbols=["XRPUSDT", "DOGEUSDT"],
        capital_pct=0.05, risk_level="alto", vol_profile="Altcoins de volatilidad inestable/alta", slippage_bps=6,
        differentiator="Satélite B: la misma tendencia, activa solo cuando la volatilidad de BTC a 14 días supera 40 % (hipótesis a probar).",
        params=dict(fast=24, slow=96, roc_n=72, stop_pct=0.04, trail_start=0.05, trail_margin=0.025),
        risk=dict(max_drawdown=0.15, action="pause_and_resume", cooldown_bars=168, max_strikes=3, strike_window_bars=720, max_loss_initial=0.20, max_turnover_month=4.0), gate=dict(type="btc_vol", symbol="BTCUSDT", lookback_days=14, threshold=0.40),
    ),
]
