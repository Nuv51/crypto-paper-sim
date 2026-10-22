"""Índice pasivo — BACKTEST EN FRÍO (2026-01-01 → 2026-10-11 (hasta el 10 de octubre)) (generado por scripts/make_universe_2025.py; no editar a mano).

Mismos tres bots, mismos parámetros y mismas reglas de ejecución que `config_index.py`, pero con el universo y las
capitalizaciones tal como se habrían visto el 2026-01-01 (ver BACKTEST_2025.md). Capitalización: exacta de CoinMarketCap
para las monedas de su Top-20 de ese día; para el resto, estimada como (cap de hoy / precio de hoy) × precio del cierre previo
(aproximación: supone el mismo suministro circulante; sobrestima monedas con desbloqueos grandes desde entonces).
"""

PORTFOLIO_CAPITAL = 30_000.0      # 3 bots × 10,000 USDT FICTICIOS
INTERVAL = "1h"
PORTFOLIO_RISK = dict(max_drawdown=None, cooldown_bars=168)

# Capitalización al inicio del periodo en USD, de mayor a menor.
CAPS_USD = {
    "BTCUSDT": 1772.003e9,  # cmc
    "ETHUSDT": 362.132e9,  # cmc
    "BNBUSDT": 118.872e9,  # cmc
    "XRPUSDT": 113.946e9,  # cmc
    "SOLUSDT": 71.386e9,  # cmc
    "TRXUSDT": 27.132e9,  # cmc
    "DOGEUSDT": 21.300e9,  # cmc
    "ADAUSDT": 12.803e9,  # cmc
    "BCHUSDT": 11.832e9,  # cmc
    "LINKUSDT": 8.912e9,  # cmc
    "ZECUSDT": 8.644e9,  # cmc
    "XLMUSDT": 6.753e9,  # cmc
    "LTCUSDT": 6.123e9,  # cmc
    "SUIUSDT": 5.881e9,  # estimada
    "AVAXUSDT": 5.638e9,  # estimada
    "HBARUSDT": 4.710e9,  # estimada
    "SHIBUSDT": 4.104e9,  # estimada
    "UNIUSDT": 3.633e9,  # estimada
    "DOTUSDT": 3.119e9,  # estimada
    "ENAUSDT": 2.615e9,  # estimada
    "TAOUSDT": 2.535e9,  # estimada
    "AAVEUSDT": 2.314e9,  # estimada
    "NEARUSDT": 1.952e9,  # estimada
    "WLDUSDT": 1.898e9,  # estimada
    "ETCUSDT": 1.820e9,  # estimada
    "PEPEUSDT": 1.681e9,  # estimada
    "ICPUSDT": 1.635e9,  # estimada
    "APTUSDT": 1.519e9,  # estimada
    "ARBUSDT": 1.313e9,  # estimada
    "POLUSDT": 1.100e9,  # estimada
    "FILUSDT": 1.099e9,  # estimada
    "ATOMUSDT": 1.045e9,  # estimada
    "ALGOUSDT": 1.021e9,  # estimada
    "QNTUSDT": 0.985e9,  # estimada
    "VETUSDT": 0.875e9,  # estimada
    "NEXOUSDT": 0.871e9,  # estimada
    "SEIUSDT": 0.758e9,  # estimada
    "RENDERUSDT": 0.659e9,  # estimada
    "ETHFIUSDT": 0.659e9,  # estimada
    "OPUSDT": 0.645e9,  # estimada
    "BONKUSDT": 0.644e9,  # estimada
    "STRKUSDT": 0.616e9,  # estimada
    "CAKEUSDT": 0.614e9,  # estimada
    "JUPUSDT": 0.611e9,  # estimada
    "CRVUSDT": 0.560e9,  # estimada
    "XTZUSDT": 0.554e9,  # estimada
    "PENGUUSDT": 0.549e9,  # estimada
    "DASHUSDT": 0.529e9,  # estimada
    "ZROUSDT": 0.525e9,  # estimada
    "LDOUSDT": 0.489e9,  # estimada
}

# Deslizamiento (bps) según el volumen diario promedio de los 30 días previos al inicio.
SLIPPAGE_BPS = {
    "BTCUSDT": 5,
    "ETHUSDT": 5,
    "BNBUSDT": 5,
    "XRPUSDT": 5,
    "SOLUSDT": 5,
    "TRXUSDT": 8,
    "DOGEUSDT": 8,
    "ADAUSDT": 8,
    "BCHUSDT": 8,
    "LINKUSDT": 8,
    "ZECUSDT": 5,
    "XLMUSDT": 25,
    "LTCUSDT": 15,
    "SUIUSDT": 8,
    "AVAXUSDT": 8,
    "HBARUSDT": 15,
    "SHIBUSDT": 25,
    "UNIUSDT": 15,
    "DOTUSDT": 15,
    "ENAUSDT": 15,
    "TAOUSDT": 15,
    "AAVEUSDT": 15,
    "NEARUSDT": 15,
    "WLDUSDT": 15,
    "ETCUSDT": 25,
    "PEPEUSDT": 8,
    "ICPUSDT": 15,
    "APTUSDT": 15,
    "ARBUSDT": 15,
    "POLUSDT": 25,
    "FILUSDT": 15,
    "ATOMUSDT": 25,
    "ALGOUSDT": 25,
    "QNTUSDT": 40,
    "VETUSDT": 40,
    "NEXOUSDT": 40,
    "SEIUSDT": 15,
    "RENDERUSDT": 25,
    "ETHFIUSDT": 25,
    "OPUSDT": 25,
    "BONKUSDT": 25,
    "STRKUSDT": 25,
    "CAKEUSDT": 25,
    "JUPUSDT": 40,
    "CRVUSDT": 25,
    "XTZUSDT": 40,
    "PENGUUSDT": 15,
    "DASHUSDT": 15,
    "ZROUSDT": 25,
    "LDOUSDT": 25,
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
