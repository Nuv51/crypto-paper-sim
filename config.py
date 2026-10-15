"""Configuración del portafolio simulado. Edita aquí capital, monedas y parámetros.

El % de capital y los controles de riesgo salen del glosario del proyecto (puntos de partida para
SIMULAR, no recomendaciones). Los 5 bots restantes (arbitraje spot-futuro, stablecoins, market making,
ML y arbitraje cross-exchange con XRP) necesitan datos que este simulador v1 aún no consume
(funding rate, libro de órdenes, varios exchanges a la vez): se agregan en la siguiente iteración.
"""

PORTFOLIO_CAPITAL = 10_000.0   # USDT FICTICIOS. Lo no asignado queda como reserva para los otros bots.
INTERVAL = "1h"

BOTS = [
    dict(
        id="b03_dca", kind="dca", name="DCA Majors", exchange="bitso",
        symbols=["BTCUSDT", "ETHUSDT"], capital_pct=0.10, risk_level="bajo",
        vol_profile="Majors (volatilidad baja-media)", slippage_bps=2,
        differentiator="Compra periódica de monto fijo, sin señales ni stop. Es acumulación, no 'edge'.",
        params=dict(interval_hours=168, contribution_pct=0.03),      # 3% del capital del bot cada semana
        risk=dict(max_drawdown=0.45, action="flag_only"),        # revisión manual, sin stop-loss
    ),
    dict(
        id="b04_grid", kind="grid", name="Grid ETH", exchange="binance",
        symbols=["ETHUSDT"], capital_pct=0.12, risk_level="medio",
        vol_profile="Volatilidad acotada / en consolidación", slippage_bps=3,
        differentiator="Puramente mecánico por niveles de precio, sin indicadores. Gana en rango, sufre en tendencia.",
        params=dict(range_pct=0.10, n_levels=16, capital_use=0.95, stop_buffer=0.02, recenter_wait_bars=72),
        risk=dict(max_drawdown=0.10, action="liquidate_and_halt"),
    ),
    dict(
        id="b05_meanrev", kind="meanrev", name="Reversión a la media", exchange="kucoin",
        symbols=["BNBUSDT", "ADAUSDT"], capital_pct=0.10, risk_level="medio",
        vol_profile="Altcoins de volatilidad estable/predecible", slippage_bps=5,
        differentiator="Señal activa (RSI + Bollinger) que decide cuándo entrar; compra caídas. Falla si la caída es el inicio de una tendencia.",
        params=dict(rsi_buy=30, tp_pct=0.04, stop_min=0.02, stop_max=0.03, max_positions=2),
        risk=dict(max_drawdown=0.10, action="liquidate_and_halt"),
    ),
    dict(
        id="b07_trend", kind="trend", name="Tendencia / Momentum", exchange="binance",
        symbols=["SOLUSDT", "AVAXUSDT"], capital_pct=0.08, risk_level="alto",
        vol_profile="Altcoins de volatilidad inestable/alta", slippage_bps=6,
        differentiator="Cruce lento de EMAs (días) + momentum; trailing stop. Compra fuerza, lo contrario del bot #5.",
        params=dict(fast=24, slow=96, roc_n=72, stop_pct=0.04, trail_start=0.05, trail_margin=0.025),
        risk=dict(max_drawdown=0.15, action="liquidate_and_halt"),
    ),
    dict(
        id="b08_breakout", kind="breakout", name="Breakout dinámico", exchange="binance",
        symbols=["DOGEUSDT", "LINKUSDT"], capital_pct=0.07, risk_level="alto",
        vol_profile="Altcoins de alta volatilidad", slippage_bps=10,
        differentiator="Evento de ruptura (horas) con filtro de volumen y sizing por riesgo ATR. OJO: se parece al #7 (ambos compran fuerza); se mide la correlación entre ambos.",
        params=dict(entry_n=48, exit_n=24, atr_mult=1.75, vol_mult=1.5, risk_pct=0.0075, max_pos_frac=0.5),
        risk=dict(max_drawdown=0.17, action="pause_and_resume", cooldown_bars=168),   # pausa obligatoria de 7 días
    ),
]
