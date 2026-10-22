"""Configuración del SIMULADOR AJUSTADO V1 (dinero FICTICIO, 10,000 USDT, velas de 1 h).

Qué es: el candidato que salió de los backtests en frío V2/V3 (BACKTEST_V3_RESULTADOS.md): el núcleo de bajo costo SIN los
satélites (grid/tendencia), SIN las estables y SIN el filtro de tendencia (el filtro SMA200 no pasó D5). Es la variante
"V3-ref" de esos backtests, puesta a correr hacia adelante, que es la única prueba que ya no está contaminada.

  a01 · DCA semanal BTC+ETH (Bitso)                 20 %
  a02 · Índice Top-25 por capitalización (Binance)  30 %   rebalanceo trimestral (90 días)
  a03 · Carry BTC spot-perpetuo (KuCoin)            25 %
  a04 · Carry ETH spot-perpetuo (KuCoin)            15 %
  a05 · Efectivo (reserva, no opera)                10 %   cuenta en el equity y el ROI (como en los backtests)

Los pesos 20/30/25/15/10 se fijaron en BACKTEST_V3.md ANTES de correr nada y NO se afinan durante la prueba. Los parámetros de
cada bot son los de V2/V3-ref (mismos que los bots equivalentes de los otros simuladores donde existen).

UNIVERSO DEL ÍNDICE: el mismo congelado del simulador indexado (config_index.py: Top-25 por capitalización de CoinGecko al
2026-10-20, todas verificadas como TRADING en Binance con ≥ 365 días de historia, sin stablecoins ni tokens de exchanges). No se
reconstituye durante la prueba; sesgo de supervivencia como en el indexado.

SOLAPAMIENTO CON LOS OTROS SIMULADORES (a propósito, para poder compararlos): a01 usa los mismos parámetros que el DCA del
simulador actual; a02 es el índice Top-25 del indexado pero con rebalanceo trimestral (no mensual); a03/a04 son carry como el
del actual (BTC) y el del dinámico (ETH, con el umbral 3 % APR de V2). Lo único realmente distinto es la mezcla y los pesos.

Cambiar CUALQUIER parámetro invalida el estado guardado (a propósito); se reinicia con la opción `reiniciar=ajustado` del flujo.
"""
import config_index as _ix

PORTFOLIO_CAPITAL = 10_000.0                     # USDT FICTICIOS
INTERVAL = "1h"
PORTFOLIO_RISK = dict(max_drawdown=None, cooldown_bars=168)       # sin freno global, igual que en los backtests V3

_TOP25 = _ix.TOP25

BOTS = [
    dict(
        id="a01_dca", kind="dca", name="DCA BTC+ETH", exchange="bitso",
        symbols=["BTCUSDT", "ETHUSDT"], capital_pct=0.20, risk_level="bajo",
        vol_profile="Majors (volatilidad baja-media)", slippage_bps=2,
        differentiator="Beta · compra semanal de monto fijo (3 % del capital del bot), sin señales ni filtro. Mismos parámetros que el DCA del simulador actual.",
        params=dict(interval_hours=168, contribution_pct=0.03),
        risk=dict(max_drawdown=0.45, action="flag_only"),
    ),
    dict(
        id="a02_index_cap25", kind="index", name="Índice Top-25 (capitalización) · rebalanceo trimestral", exchange="binance",
        symbols=_TOP25, caps_usd={s: _ix.CAPS_USD[s] for s in _TOP25}, slippage_map_bps={s: _ix.SLIPPAGE_BPS[s] for s in _TOP25},
        slippage_bps=10, capital_pct=0.30, risk_level="medio",
        vol_profile="Mercado amplio: domina BTC/ETH (tope 30 % cada una)",
        differentiator="Beta · mismo universo que el índice del simulador indexado pero con rebalanceo cada 90 días (menos costo que cada 30). Sin filtro de tendencia.",
        params=dict(weighting="cap", cap_max=0.30, rebalance_hours=2160, cash_buffer=0.005, min_trade_usdt=8.0, min_weight=0.0008),
        risk=dict(max_drawdown=0.50, action="flag_only"),
    ),
    dict(
        id="a03_carry_btc", kind="carry", name="Carry BTC spot-perpetuo", exchange="kucoin",
        symbols=["BTCUSDT", "BTCUSDT~PERP"], capital_pct=0.25, risk_level="bajo",
        vol_profile="Majors · market-neutral (cobra funding, no apuesta a dirección)", slippage_bps=2,
        differentiator="Defensivo · largo spot + corto perpetuo BTC, cobra funding. 25 % del capital (en V2 era 12.5 %). Con funding bajo no opera y su capital queda ocioso.",
        params=dict(perp_taker=0.0006, perp_slip_bps=2.0, leverage=2.0, avg_n=3, min_apr=0.05,
                    min_hold_days=10, neg_periods_exit=3, margin_stress=0.8),
        risk=dict(max_drawdown=0.05, action="pause_and_resume", cooldown_bars=168, max_strikes=3, strike_window_bars=720),
    ),
    dict(
        id="a04_carry_eth", kind="carry", name="Carry ETH spot-perpetuo", exchange="kucoin",
        symbols=["ETHUSDT", "ETHUSDT~PERP"], capital_pct=0.15, risk_level="bajo",
        vol_profile="Majors · market-neutral (cobra funding, no apuesta a dirección)", slippage_bps=2,
        differentiator="Defensivo · mismo carry sobre ETH, umbral 3 % APR y permanencia mínima de 20 días (los de V2). 15 % del capital.",
        params=dict(perp_taker=0.0006, perp_slip_bps=2.0, leverage=2.0, avg_n=3, min_apr=0.03,
                    min_hold_days=20, neg_periods_exit=3, margin_stress=0.8),
        risk=dict(max_drawdown=0.05, action="pause_and_resume", cooldown_bars=672, max_strikes=3, strike_window_bars=2880),
    ),
    dict(
        id="a05_cash", kind="cash", name="Efectivo (reserva)", exchange="binance",
        symbols=["BTCUSDT"], capital_pct=0.10, risk_level="bajo",
        vol_profile="Sin exposición al mercado",
        differentiator="Reserva del 10 % que no opera ni rinde. Se incluye para que el ROI y el drawdown cuenten los 10,000 USDT completos, como en los backtests.",
        params={}, risk=dict(),
    ),
]
