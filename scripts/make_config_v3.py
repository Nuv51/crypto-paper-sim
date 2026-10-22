"""Genera config_v3_<año>.py y config_v3ref_<año>.py (V3, ver BACKTEST_V3.md) a partir del universo ya fijado de V2.

  python scripts/make_config_v3.py [año ...]        (sin argumentos: 2019..2026)

V3 = núcleo de V2 sin satélites ni estables, con más peso al carry y filtro de tendencia (BTC sobre su media de 200 días) en las
patas de beta (DCA e índice). V3-ref = exactamente lo mismo SIN el filtro (control para medir H1). Mismas monedas, mismos
parámetros de cada bot que V2; solo cambian pesos, bots presentes y el filtro.
"""
from __future__ import annotations

import importlib
import pprint
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GATE = dict(type="btc_sma", symbol="BTCUSDT", sma_days=200)
WEIGHTS = {"v01_dca": 0.20, "v05_index_cap25": 0.30, "v02_carry_btc": 0.25, "v03_carry_eth": 0.15}        # 10 % queda en efectivo
IDS = {"v01_dca": "w01_dca", "v02_carry_btc": "w02_carry_btc", "v03_carry_eth": "w03_carry_eth", "v05_index_cap25": "w04_index_cap25"}
DIFF = {
    "w01_dca": "Beta · DCA semanal BTC+ETH. V3: con filtro de tendencia (compra solo con BTC sobre su media de 200 días; liquida al perderla).",
    "w04_index_cap25": "Beta · índice Top-25 por capitalización, rebalanceo trimestral. V3: con filtro de tendencia (a efectivo si BTC pierde su media de 200 días).",
    "w02_carry_btc": "Defensivo · largo spot + corto perpetuo BTC. V3: 25 % del capital (en V2, 12.5 %).",
    "w03_carry_eth": "Defensivo · carry ETH. V3: 15 % del capital (en V2, 7.5 %).",
}


def build(year: int, gated: bool) -> str:
    v2 = importlib.import_module(f"config_v2_{year}")
    by = {b["id"]: b for b in v2.BOTS}
    bots = []
    for old, new in IDS.items():
        if old not in by:
            continue                                      # p. ej. sin carry en 2019
        b = dict(by[old], id=new, capital_pct=WEIGHTS[old], differentiator=DIFF[new])
        b.pop("gate", None)
        if gated and old in ("v01_dca", "v05_index_cap25"):
            b["gate"] = dict(GATE)
        bots.append(b)
    name = "V3" if gated else "V3-ref (control: V3 sin filtro de tendencia)"
    body = pprint.pformat(bots, width=140, sort_dicts=False)
    return f'''"""Simulador {name} — BACKTEST EN FRÍO {year} (generado por scripts/make_config_v3.py; no editar a mano).

Universo y parámetros heredados de config_v2_{year}.py; ver BACKTEST_V3.md.
"""

PORTFOLIO_CAPITAL = 10_000.0      # USDT FICTICIOS
INTERVAL = "1h"
PORTFOLIO_RISK = dict(max_drawdown=None, cooldown_bars=168)

BOTS = {body}
'''


def main():
    years = [int(a) for a in sys.argv[1:]] or list(range(2019, 2027))
    for y in years:
        (ROOT / f"config_v3_{y}.py").write_text(build(y, True))
        (ROOT / f"config_v3ref_{y}.py").write_text(build(y, False))
        print(y, "ok")


if __name__ == "__main__":
    main()
