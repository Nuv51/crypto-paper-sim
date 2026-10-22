"""Genera config_v2_<año>.py (backtest V2 2019-2024) con las reglas de BACKTEST_V2_2019_2024.md.

  python scripts/make_config_v2.py [año ...]        (sin argumentos: 2019..2024)

Entradas (backtest_v2/inputs/): caps_cmc_<foto>.json y binance_pit<año>.json. Nada aquí mira precios posteriores al 1 de enero:
solo si la moneda existe, cuánto historial tenía antes de esa fecha y si cotiza todo el año.
Salida extra: backtest_v2/universe_<año>.json (quién entró, quién quedó fuera y por qué).
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_universe_2025 import EXCLUDE, tier                       # noqa: E402
from pit_v2 import MORE_EXCLUDE, SNAP                               # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
IN = ROOT / "backtest_v2" / "inputs"
MIN_HISTORY_DAYS = 180          # regla 1 (V1 usaba 365; con 365 el universo de 2019 quedaría en ~6 monedas)
MIN_ELIGIBLE = 8                # si hay menos, el backtest de ese año no se corre
CARRY_FROM = 2020               # el archivo de futuros de Binance empieza en 2020-01
BAD = EXCLUDE | MORE_EXCLUDE | {"LUNA", "LUNC"}   # LUNA: el símbolo se reutilizó en 2022 (Terra clásica → LUNC; Terra 2.0 → LUNA)


def eligible(year: int):
    caps = json.loads((IN / f"caps_cmc_{SNAP[year]}.json").read_text())["caps_usd"]
    pit = json.loads((IN / f"binance_pit{year}.json").read_text())
    asof = date(year, 1, 1)
    inv = {"IOTA": "MIOTA", "BSV": "BCHSV", "XNO": "NANO"}
    rows, excl = [], []
    for cmc_sym, cap in caps.items():
        base = {"MIOTA": "IOTA", "BCHSV": "BSV", "BCHABC": "BCH", "NANO": "XNO"}.get(cmc_sym, cmc_sym)
        if cmc_sym in BAD or base in BAD:
            excl.append((base, "estable, fondo, token de otro exchange o símbolo reutilizado")); continue
        v = pit.get(base)
        if not v:
            continue                                   # fuera del Top-120 sondeado
        if v.get("status") != "OK":
            excl.append((base, "no existe en Binance spot USDT")); continue
        first = date.fromisoformat(v["first_day"])
        if (asof - first).days < MIN_HISTORY_DAYS:
            excl.append((base, f"historial < {MIN_HISTORY_DAYS} días al {asof} (listada {first})")); continue
        nd = 366 if (year % 4 == 0) else 365
        if v.get("days_period", 0) < nd - 5:
            excl.append((base, f"dejó de cotizar o tiene huecos en el año ({v.get('days_period')} de {nd} días; última {v.get('last_day')})")); continue
        if not v.get("close_pre") or not v.get("vol30_pre"):
            excl.append((base, "sin precio/volumen previo")); continue
        rows.append(dict(base=base, symbol=base + "USDT", cap=float(cap), first_day=v["first_day"], vol30=v["vol30_pre"],
                         slippage_bps=tier(v["vol30_pre"])))
    rows.sort(key=lambda r: -r["cap"])
    return rows, excl, pit


def build(year: int) -> str:
    rows, excl, pit = eligible(year)
    if len(rows) < MIN_ELIGIBLE:
        raise SystemExit(f"{year}: solo {len(rows)} monedas elegibles (< {MIN_ELIGIBLE}); el backtest de ese año no se corre")
    top25 = rows[:25]
    # Estables del bot v04: de USDC/TUSD/BUSD/PAX/USDP/FDUSD, las que cotizan TODO el año y tenían ≥30 días de historial; hasta 2,
    # las de mayor volumen de los 30 días previos (USDC dejó de cotizar contra USDT en Binance durante partes de 2022 y 2023).
    asof = date(year, 1, 1)
    nd = 366 if year % 4 == 0 else 365
    cand = []
    for b in ("USDC", "TUSD", "BUSD", "PAX", "USDP", "FDUSD"):
        v = pit.get(b) or {}
        if v.get("status") == "OK" and v.get("vol30_pre") and (asof - date.fromisoformat(v["first_day"])).days >= 30 and v.get("days_period", 0) >= nd - 5:
            cand.append((v["vol30_pre"], b + "USDT"))
    cand.sort(reverse=True)
    stables = [s_ for _, s_ in cand[:2]]
    # Si ninguna cotiza todo el año (2023: Binance dejó de listar USDC/TUSD/USDP/PAX contra USDT en marzo), el bot v04 se omite
    # y su 10 % queda en efectivo (igual que el carry en 2019). El ROI titular sigue siendo sobre los 10,000 completos.
    trend = [r["symbol"] for r in rows if r["base"] not in ("BTC", "ETH", "BNB")][:2]
    carry = year >= CARRY_FROM
    meta = dict(year=year, snapshot=SNAP[year], n_eligible=len(rows), index=[r["symbol"] for r in top25], stables=stables, trend=trend,
                carry=carry, excluded=[dict(base=b, reason=r) for b, r in excl],
                top25=[dict(base=r["base"], cap=r["cap"], first_day=r["first_day"], slippage_bps=r["slippage_bps"]) for r in top25])
    (ROOT / "backtest_v2" / f"universe_{year}.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    caps = "\n".join(f'    "{r["symbol"]}": {r["cap"] / 1e9:.4f}e9,' for r in top25)
    slip = "\n".join(f'    "{r["symbol"]}": {r["slippage_bps"]},' for r in top25)
    carry_bots = f'''
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
    ),''' if carry else '''
    # Sin carry en este año: el archivo de futuros de Binance empieza en 2020-01 (ver BACKTEST_V2_2019_2024.md).
    # Su 20 % del capital queda en efectivo sin rendimiento; el ROI del portafolio se mide sobre los 10,000 completos.'''
    sat_risk = lambda mdd: f"dict(max_drawdown={mdd}, action=\"pause_and_resume\", cooldown_bars=168, max_strikes=3, strike_window_bars=720, max_loss_initial=0.20, max_turnover_month=4.0)"
    gate = 'dict(type="btc_vol", symbol="BTCUSDT", lookback_days=14, threshold=0.40)'
    trend_syms = json.dumps(trend)
    stable_bot = ('''    dict(
        id="v04_stable", kind="stable", name="Stablecoins · peg", exchange="binance", symbols=%s,
        capital_pct=0.10, risk_level="bajo", vol_profile="Stablecoins (volatilidad mínima; riesgo de cola = de-peg)", slippage_bps=1,
        differentiator="Núcleo: compra desvíos del peg y vende al volver. Igual a V1 b02 (umbral 0.30 %%); solo cambian las monedas disponibles cada año.",
        params=dict(entry_dev=0.003, exit_dev=0.0005, stop_pct=0.01, guard_dev=0.015, depeg=0.02, depeg_bars=6, max_hold_bars=72),
        risk=dict(max_drawdown=0.02, action="pause_and_resume", cooldown_bars=168, max_strikes=3, strike_window_bars=720),
    ),''' % json.dumps(stables)) if stables else "    # Sin estable que cotice todo el año (2023): v04 omitido; su 10 %% queda en efectivo (ver BACKTEST_V2_2019_2024.md)."
    return f'''"""Simulador V2 · Reestructurado low cost — BACKTEST EN FRÍO {year} (generado por scripts/make_config_v2.py; no editar a mano).

Universo y monedas decididos con la información del {year}-01-01 (foto de CoinMarketCap del {SNAP[year]}; Binance spot) según
BACKTEST_V2_2019_2024.md. Parámetros de cada bot = los de V1 salvo los cambios declarados allí.
"""

PORTFOLIO_CAPITAL = 10_000.0      # USDT FICTICIOS
INTERVAL = "1h"
PORTFOLIO_RISK = dict(max_drawdown=None, cooldown_bars=168)

# Capitalización de la foto (USD), de mayor a menor: Top-25 de las monedas elegibles ({len(rows)} elegibles).
CAPS_USD = {{
{caps}
}}
SLIPPAGE_BPS = {{
{slip}
}}
INDEX_SYMBOLS = list(CAPS_USD)

BOTS = [
    dict(
        id="v01_dca", kind="dca", name="DCA BTC+ETH", exchange="bitso", symbols=["BTCUSDT", "ETHUSDT"],
        capital_pct=0.20, risk_level="bajo", vol_profile="Majors (volatilidad baja-media)", slippage_bps=2,
        differentiator="Núcleo: compra semanal de monto fijo, sin señales ni stop (acumulación, no 'edge'). Igual a V1 b03.",
        params=dict(interval_hours=168, contribution_pct=0.03), risk=dict(max_drawdown=0.45, action="flag_only"),
    ),{carry_bots}
{stable_bot}
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
        risk={sat_risk(0.10)},
    ),
    dict(
        id="v07_grid_eth_gate", kind="grid", name="Grid ETH · interruptor de volatilidad", exchange="binance", symbols=["ETHUSDT"],
        capital_pct=0.05, risk_level="medio", vol_profile="Volatilidad acotada / en consolidación", slippage_bps=3,
        differentiator="Satélite B: el mismo grid, activo solo cuando la volatilidad de BTC a 14 días supera 40 % (hipótesis a probar).",
        params=dict(range_pct=0.1, n_levels=16, capital_use=0.95, stop_buffer=0.02, recenter_wait_bars=72),
        risk={sat_risk(0.10)}, gate={gate},
    ),
    dict(
        id="v08_trend", kind="trend", name="Tendencia · siempre activo", exchange="binance", symbols={trend_syms},
        capital_pct=0.05, risk_level="alto", vol_profile="Altcoins de volatilidad inestable/alta", slippage_bps=6,
        differentiator="Satélite A: tendencia/momentum de V1 sobre las 2 mayores monedas elegibles (sin BTC, ETH ni BNB), sin interruptor.",
        params=dict(fast=24, slow=96, roc_n=72, stop_pct=0.04, trail_start=0.05, trail_margin=0.025),
        risk={sat_risk(0.15)},
    ),
    dict(
        id="v09_trend_gate", kind="trend", name="Tendencia · interruptor de volatilidad", exchange="binance", symbols={trend_syms},
        capital_pct=0.05, risk_level="alto", vol_profile="Altcoins de volatilidad inestable/alta", slippage_bps=6,
        differentiator="Satélite B: la misma tendencia, activa solo cuando la volatilidad de BTC a 14 días supera 40 % (hipótesis a probar).",
        params=dict(fast=24, slow=96, roc_n=72, stop_pct=0.04, trail_start=0.05, trail_margin=0.025),
        risk={sat_risk(0.15)}, gate={gate},
    ),
]
'''


def main():
    years = [int(a) for a in sys.argv[1:]] or sorted(SNAP)
    for y in years:
        (ROOT / f"config_v2_{y}.py").write_text(build(y))
        print(y, "ok")


if __name__ == "__main__":
    main()
