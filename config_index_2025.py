"""Índice pasivo — BACKTEST EN FRÍO 2025 (generado por scripts/make_universe_2025.py; no editar a mano).

Mismos tres bots, mismos parámetros y mismas reglas de ejecución que `config_index.py`, pero con el universo y las
capitalizaciones tal como se habrían visto el 2025-01-01 (ver BACKTEST_2025.md). Capitalización: exacta de CoinMarketCap
para las monedas de su Top-20 de ese día; para el resto, estimada como (cap de hoy / precio de hoy) × precio del 2024-12-31
(aproximación: supone el mismo suministro circulante; sobrestima monedas con desbloqueos grandes desde entonces).
"""

PORTFOLIO_CAPITAL = 30_000.0      # 3 bots × 10,000 USDT FICTICIOS
INTERVAL = "1h"
PORTFOLIO_RISK = dict(max_drawdown=None, cooldown_bars=168)

# Capitalización estimada al 2025-01-01 en USD, de mayor a menor.
CAPS_USD = {
    "BTCUSDT": 1869.921e9,  # cmc
    "ETHUSDT": 404.012e9,  # cmc
    "XRPUSDT": 133.326e9,  # cmc
    "BNBUSDT": 101.743e9,  # cmc
    "SOLUSDT": 93.606e9,  # cmc
    "DOGEUSDT": 47.819e9,  # cmc
    "ADAUSDT": 32.244e9,  # cmc
    "TRXUSDT": 22.007e9,  # cmc
    "AVAXUSDT": 15.451e9,  # cmc
    "LINKUSDT": 13.831e9,  # cmc
    "SUIUSDT": 12.866e9,  # cmc
    "XLMUSDT": 12.832e9,  # cmc
    "SHIBUSDT": 12.755e9,  # cmc
    "HBARUSDT": 11.243e9,  # cmc
    "DOTUSDT": 10.786e9,  # cmc
    "BCHUSDT": 8.902e9,  # cmc
    "UNIUSDT": 8.549e9,  # estimada
    "PEPEUSDT": 8.345e9,  # estimada
    "WLDUSDT": 8.214e9,  # estimada
    "LTCUSDT": 8.102e9,  # estimada
    "APTUSDT": 7.976e9,  # estimada
    "NEARUSDT": 6.297e9,  # estimada
    "ICPUSDT": 5.690e9,  # estimada
    "ARBUSDT": 5.089e9,  # estimada
    "AAVEUSDT": 4.903e9,  # estimada
    "TIAUSDT": 4.800e9,  # estimada
    "OPUSDT": 4.228e9,  # estimada
    "FILUSDT": 4.197e9,  # estimada
    "ETCUSDT": 3.984e9,  # estimada
    "VETUSDT": 3.613e9,  # estimada
    "ATOMUSDT": 3.363e9,  # estimada
    "ALGOUSDT": 3.096e9,  # estimada
    "FETUSDT": 3.042e9,  # estimada
    "STXUSDT": 2.914e9,  # estimada
    "SEIUSDT": 2.705e9,  # estimada
    "BONKUSDT": 2.646e9,  # estimada
    "THETAUSDT": 2.278e9,  # estimada
    "GRTUSDT": 2.183e9,  # estimada
    "INJUSDT": 2.109e9,  # estimada
    "JTOUSDT": 1.823e9,  # estimada
    "FLOKIUSDT": 1.752e9,  # estimada
    "SANDUSDT": 1.666e9,  # estimada
    "JASMYUSDT": 1.593e9,  # estimada
    "QNTUSDT": 1.504e9,  # estimada
    "LDOUSDT": 1.485e9,  # estimada
    "RUNEUSDT": 1.465e9,  # estimada
    "XTZUSDT": 1.435e9,  # estimada
    "CRVUSDT": 1.400e9,  # estimada
    "ENSUSDT": 1.388e9,  # estimada
    "IOTAUSDT": 1.314e9,  # estimada
}

# Deslizamiento (bps) según el volumen diario promedio de los 30 días previos al 2025-01-01.
SLIPPAGE_BPS = {
    "BTCUSDT": 5,
    "ETHUSDT": 5,
    "XRPUSDT": 5,
    "BNBUSDT": 5,
    "SOLUSDT": 5,
    "DOGEUSDT": 5,
    "ADAUSDT": 5,
    "TRXUSDT": 5,
    "AVAXUSDT": 5,
    "LINKUSDT": 5,
    "SUIUSDT": 5,
    "XLMUSDT": 5,
    "SHIBUSDT": 5,
    "HBARUSDT": 5,
    "DOTUSDT": 5,
    "BCHUSDT": 8,
    "UNIUSDT": 5,
    "PEPEUSDT": 5,
    "WLDUSDT": 5,
    "LTCUSDT": 5,
    "APTUSDT": 8,
    "NEARUSDT": 5,
    "ICPUSDT": 8,
    "ARBUSDT": 5,
    "AAVEUSDT": 5,
    "TIAUSDT": 8,
    "OPUSDT": 8,
    "FILUSDT": 8,
    "ETCUSDT": 8,
    "VETUSDT": 8,
    "ATOMUSDT": 8,
    "ALGOUSDT": 8,
    "FETUSDT": 8,
    "STXUSDT": 8,
    "SEIUSDT": 8,
    "BONKUSDT": 8,
    "THETAUSDT": 8,
    "GRTUSDT": 15,
    "INJUSDT": 8,
    "JTOUSDT": 15,
    "FLOKIUSDT": 5,
    "SANDUSDT": 5,
    "JASMYUSDT": 8,
    "QNTUSDT": 15,
    "LDOUSDT": 8,
    "RUNEUSDT": 8,
    "XTZUSDT": 15,
    "CRVUSDT": 5,
    "ENSUSDT": 8,
    "IOTAUSDT": 8,
}

UNIVERSE_SYMBOLS = list(CAPS_USD)
TOP25 = UNIVERSE_SYMBOLS[:25]
TOP50 = UNIVERSE_SYMBOLS[:50]

_RISK = dict(max_drawdown=0.50, action="flag_only")
_PARAMS = dict(rebalance_hours=720, cash_buffer=0.005, min_trade_usdt=8.0, min_weight=0.0008)


def _slip(symbols):
    return {s: SLIPPAGE_BPS[s] for s in symbols}


BOTS = [
    dict(
        id="i01_index_cap25", kind="index", name="Índice Top-25 (capitalización)", exchange="binance",
        symbols=TOP25, caps_usd={s: CAPS_USD[s] for s in TOP25}, slippage_map_bps=_slip(TOP25), slippage_bps=10,
        capital_pct=1 / 3, risk_level="medio",
        vol_profile="Mercado amplio: domina BTC/ETH (tope 30 % cada una)",
        differentiator="Cartera pasiva: compra el Top-25 ponderado por capitalización con tope de 30 % y rebalancea cada 30 días. "
                       "Es la referencia 'el mercado'. Comparte monedas con los otros dos índices por diseño.",
        params=dict(weighting="cap", cap_max=0.30, **_PARAMS), risk=_RISK,
    ),
    dict(
        id="i02_index_cap50", kind="index", name="Índice Top-50 (capitalización)", exchange="binance",
        symbols=TOP50, caps_usd={s: CAPS_USD[s] for s in TOP50}, slippage_map_bps=_slip(TOP50), slippage_bps=10,
        capital_pct=1 / 3, risk_level="medio",
        vol_profile="Mercado amplio con cola larga de monedas pequeñas e ilíquidas",
        differentiator="Igual que el Top-25 pero con 50 monedas. OJO: ponderar por capitalización hace que la cola pese muy poco, "
                       "así que se parece mucho al Top-25 (mide cuánto aporta ampliar el universo).",
        params=dict(weighting="cap", cap_max=0.30, **_PARAMS), risk=_RISK,
    ),
    dict(
        id="i03_index_ew25", kind="index", name="Índice Top-25 (igual peso)", exchange="binance",
        symbols=TOP25, slippage_map_bps=_slip(TOP25), slippage_bps=10,
        capital_pct=1 / 3, risk_level="medio",
        vol_profile="Mercado amplio con más peso en monedas medianas (4 % cada una)",
        differentiator="Las mismas 25 monedas que el índice por capitalización pero con 4 % cada una: apuesta más a las pequeñas "
                       "y menos a BTC/ETH. El rebalanceo mensual vende lo que subió y compra lo que bajó (puede ayudar o dañar).",
        params=dict(weighting="equal", **_PARAMS), risk=_RISK,
    ),
]
