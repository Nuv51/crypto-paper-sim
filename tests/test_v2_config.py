"""Configuraciones V2 2019-2024: gemelos idénticos salvo el interruptor, capital ≤ 100 %, universos coherentes con lo guardado."""
from __future__ import annotations

import importlib
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

YEARS = range(2019, 2027)


def test_twins_identical_except_gate_and_capital_within_budget():
    for y in YEARS:
        c = importlib.import_module(f"config_v2_{y}")
        by = {b["id"]: b for b in c.BOTS}
        assert 0.79 < sum(b["capital_pct"] for b in c.BOTS) <= 1.0 + 1e-9
        for a, b in (("v06_grid_eth", "v07_grid_eth_gate"), ("v08_trend", "v09_trend_gate")):
            assert "gate" not in by[a] and by[b]["gate"] == dict(type="btc_vol", symbol="BTCUSDT", lookback_days=14, threshold=0.40)
            assert by[a]["params"] == by[b]["params"] and by[a]["risk"] == by[b]["risk"] and by[a]["symbols"] == by[b]["symbols"]
            assert by[a]["capital_pct"] == by[b]["capital_pct"] == 0.05
            assert by[a]["risk"]["max_loss_initial"] == 0.20 and by[a]["risk"]["max_turnover_month"] == 4.0
        assert by["v05_index_cap25"]["params"]["rebalance_hours"] == 2160
        assert ("v02_carry_btc" in by) == (y >= 2020) and ("v03_carry_eth" in by) == (y >= 2020)


def test_universe_files_match_configs_and_rules():
    for y in YEARS:
        c = importlib.import_module(f"config_v2_{y}")
        u = json.loads((ROOT / "backtest_v2" / f"universe_{y}.json").read_text())
        assert list(c.CAPS_USD) == u["index"] and len(u["index"]) == min(25, u["n_eligible"]) and u["n_eligible"] >= 8
        caps = list(c.CAPS_USD.values())
        assert caps == sorted(caps, reverse=True)
        assert set(c.SLIPPAGE_BPS) == set(c.CAPS_USD)
        for t in u["top25"]:
            assert (date(y, 1, 1) - date.fromisoformat(t["first_day"])).days >= 180      # ≥ 180 días de historial al inicio
        bad = {"USDT", "USDC", "BUSD", "TUSD", "LUNA", "WBTC", "FDUSD", "LEO", "CRO"}
        assert not bad & {t["base"] for t in u["top25"]}
        by = {b["id"]: b for b in c.BOTS}
        assert not {"BTCUSDT", "ETHUSDT", "BNBUSDT"} & set(by["v08_trend"]["symbols"]) and len(by["v08_trend"]["symbols"]) == 2
        assert ("v04_stable" in by) == bool(u["stables"]) and (y != 2023 or "v04_stable" not in by)
