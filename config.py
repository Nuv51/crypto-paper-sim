"""Configuración del portafolio simulado. Edita aquí capital, monedas y parámetros.

El % de capital y los controles de riesgo salen del glosario del proyecto (puntos de partida para
SIMULAR, no recomendaciones). Asignación del glosario: 15/15/8/12/10/8/8/7/5/10 % = 98 %, que al final de este archivo se escala a 100 %. Antes quedaba 2 %
sin desplegar como colchón. Cambiar CUALQUIER parámetro de un bot invalida el estado guardado de la simulación
en la nube (a propósito: no se afinan parámetros a mitad de una prueba hacia adelante); reinicia con la opción
`fresh` del workflow.

Símbolos con "~" son fuentes especiales (ver sim/data.py): BTCUSDT~PERP = perpetuo de KuCoin con funding,
XRP~RAIL = foto del mercado XRP en Bitso/Binance/KuCoin.
"""

PORTFOLIO_CAPITAL = 10_000.0   # USDT FICTICIOS. Lo no asignado queda como reserva.
INTERVAL = "1h"

# Freno global del portafolio completo: si el equity total cae 10 % desde su máximo, se liquida TODO, se pausa 7 días
# (168 barras de 1 h) y todos los bots reanudan solos con el máximo reiniciado. No requiere ninguna acción manual.
PORTFOLIO_RISK = dict(max_drawdown=0.10, cooldown_bars=168)

BOTS = [
    dict(
        id="b01_carry", kind="carry", name="Carry spot-perpetuo", exchange="kucoin",
        symbols=["BTCUSDT", "BTCUSDT~PERP"], capital_pct=0.15, risk_level="bajo",
        vol_profile="Majors · market-neutral (cobra funding, no apuesta a dirección)", slippage_bps=2,
        differentiator="Único bot con pata corta (perpetuo): gana funding, no dirección. Solo entra si el funding cubre sus costos de entrada/salida.",
        params=dict(perp_taker=0.0006, perp_slip_bps=2.0, leverage=2.0, avg_n=3, min_apr=0.05,
                    min_hold_days=10, neg_periods_exit=3, margin_stress=0.8),
        risk=dict(max_drawdown=0.05, action="pause_and_resume", cooldown_bars=168, max_strikes=3, strike_window_bars=720),
    ),
    dict(
        id="b02_stable", kind="stable", name="Stablecoins · peg", exchange="binance",
        symbols=["USDCUSDT", "FDUSDUSDT"], capital_pct=0.15, risk_level="bajo",
        vol_profile="Stablecoins (volatilidad mínima; riesgo de cola = de-peg)", slippage_bps=1,
        differentiator="Compra desvíos del peg bajo 1.00 y vende al volver. Con comisiones de 0.1% por lado solo opera desvíos grandes; puede pasar semanas sin operar.",
        params=dict(entry_dev=0.0030, exit_dev=0.0005, stop_pct=0.010, guard_dev=0.015, depeg=0.020,
                    depeg_bars=6, max_hold_bars=72),
        risk=dict(max_drawdown=0.02, action="pause_and_resume", cooldown_bars=168, max_strikes=3, strike_window_bars=720),
    ),
    dict(
        id="b03_dca", kind="dca", name="DCA Majors", exchange="bitso",
        symbols=["BTCUSDT", "ETHUSDT"], capital_pct=0.08, risk_level="bajo",
        vol_profile="Majors (volatilidad baja-media)", slippage_bps=2,
        differentiator="Compra periódica de monto fijo, sin señales ni stop. Es acumulación, no 'edge'.",
        params=dict(interval_hours=168, contribution_pct=0.03),      # 3% del capital del bot cada semana
        risk=dict(max_drawdown=0.45, action="flag_only"),        # solo alerta informativa: DCA no tiene stop por diseño
    ),
    dict(
        id="b04_grid", kind="grid", name="Grid ETH", exchange="binance",
        symbols=["ETHUSDT"], capital_pct=0.12, risk_level="medio",
        vol_profile="Volatilidad acotada / en consolidación", slippage_bps=3,
        differentiator="Puramente mecánico por niveles de precio, sin indicadores. Gana en rango, sufre en tendencia.",
        params=dict(range_pct=0.10, n_levels=16, capital_use=0.95, stop_buffer=0.02, recenter_wait_bars=72),
        risk=dict(max_drawdown=0.10, action="pause_and_resume", cooldown_bars=168, max_strikes=3, strike_window_bars=720),
    ),
    dict(
        id="b05_meanrev", kind="meanrev", name="Reversión a la media", exchange="kucoin",
        symbols=["BNBUSDT", "ADAUSDT"], capital_pct=0.10, risk_level="medio",
        vol_profile="Altcoins de volatilidad estable/predecible", slippage_bps=5,
        differentiator="Señal activa (RSI + Bollinger) que decide cuándo entrar; compra caídas. Falla si la caída es el inicio de una tendencia.",
        params=dict(rsi_buy=30, tp_pct=0.04, stop_min=0.02, stop_max=0.03, max_positions=2),
        risk=dict(max_drawdown=0.10, action="pause_and_resume", cooldown_bars=168, max_strikes=3, strike_window_bars=720),
    ),
    dict(
        id="b06_mm", kind="mm", name="Market making BTC", exchange="binance",
        symbols=["BTCUSDT"], capital_pct=0.08, risk_level="medio",
        vol_profile="Majors líquidos (spread estrecho)", slippage_bps=1,
        differentiator="Re-cotiza compra y venta cada hora alrededor del precio, con control de inventario (no usa niveles fijos como el grid #4). Con velas de 1 h es solo una aproximación: no valida un market maker real.",
        params=dict(half_spread=0.0015, quote_frac=0.10, target_inv=0.50, quote_stop_dev=0.20,
                    rebalance_dev=0.30, vol_guard=0.012),
        risk=dict(max_drawdown=0.12, action="pause_and_resume", cooldown_bars=168, max_strikes=3, strike_window_bars=720),
    ),
    dict(
        id="b07_trend", kind="trend", name="Tendencia / Momentum", exchange="binance",
        symbols=["SOLUSDT", "AVAXUSDT"], capital_pct=0.08, risk_level="alto",
        vol_profile="Altcoins de volatilidad inestable/alta", slippage_bps=6,
        differentiator="Cruce lento de EMAs (días) + momentum; trailing stop. Compra fuerza, lo contrario del bot #5.",
        params=dict(fast=24, slow=96, roc_n=72, stop_pct=0.04, trail_start=0.05, trail_margin=0.025),
        risk=dict(max_drawdown=0.15, action="pause_and_resume", cooldown_bars=168, max_strikes=3, strike_window_bars=720),
    ),
    dict(
        id="b08_breakout", kind="breakout", name="Breakout dinámico", exchange="binance",
        symbols=["DOGEUSDT", "LINKUSDT"], capital_pct=0.07, risk_level="alto",
        vol_profile="Altcoins de alta volatilidad", slippage_bps=10,
        differentiator="Evento de ruptura (horas) con filtro de volumen y sizing por riesgo ATR. OJO: se parece al #7 (ambos compran fuerza); se mide la correlación entre ambos.",
        params=dict(entry_n=48, exit_n=24, atr_mult=1.75, vol_mult=1.5, risk_pct=0.0075, max_pos_frac=0.5),
        risk=dict(max_drawdown=0.17, action="pause_and_resume", cooldown_bars=168, max_strikes=3, strike_window_bars=720),   # liquida, pausa 7 días y reanuda solo; 3 rupturas en 30 días = retirado
    ),
    dict(
        id="b09_ml", kind="ml", name="Señales ML", exchange="binance",
        symbols=["BTCUSDT", "ETHUSDT", "XRPUSDT"], capital_pct=0.05, risk_level="alto",
        vol_profile="Majors líquidos (modelo común entrenado con las tres monedas)", slippage_bps=5,
        differentiator="Única estrategia que aprende de los datos: regresión logística reentrenada cada 14 días (walk-forward) y solo opera con P ≥ 0.60. Registra su acierto fuera de muestra; puede pasar semanas sin operar.",
        params=dict(horizon=6, train_bars=480, retrain_bars=336, thr=0.60, stop_pct=0.03, l2=5.0),
        risk=dict(max_drawdown=0.12, action="pause_and_resume", cooldown_bars=168, max_strikes=3, strike_window_bars=720),
    ),
    dict(
        id="b10_xrp", kind="xrp_rail", name="Arbitraje XRP Bitso", exchange="cross",
        symbols=["XRP~RAIL"], capital_pct=0.10, risk_level="bajo",
        vol_profile="Spread entre exchanges (XRP como riel de traslado)", slippage_bps=0,
        differentiator="Mide si el spread Bitso ↔ Binance/KuCoin supera comisiones (cota superior optimista, una foto del mercado por corrida). Opera por spread, no por dirección.",
        params=dict(threshold=0.003, trade_frac=0.30, slip_bps=5.0, max_imbalance=0.35, rebalance_cost=0.0005),
        risk=dict(max_drawdown=0.05, action="pause_and_resume", cooldown_bars=168, max_strikes=3, strike_window_bars=720),
    ),
]


# El glosario suma 98 %. Para que la simulación arranque con los 10,000 USDT completos (sin colchón sin desplegar),
# los % se escalan proporcionalmente a 100 %: cada bot conserva su peso relativo del glosario.
_TOTAL_PCT = sum(b["capital_pct"] for b in BOTS)
for _b in BOTS:
    _b["capital_pct"] = _b["capital_pct"] / _TOTAL_PCT
