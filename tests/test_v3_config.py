"""Generador de configuraciones V3 (V3 y V3-ref) sobre el universo de V2."""
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _mod(prefix, y):
    return importlib.import_module(f"{prefix}_{y}")


def test_v3_vs_ref_only_differ_by_gate():
    for y in range(2019, 2027):
        a, b = _mod("config_v3", y).BOTS, _mod("config_v3ref", y).BOTS
        assert [x["id"] for x in a] == [x["id"] for x in b]
        for x, r in zip(a, b):
            assert x["capital_pct"] == r["capital_pct"]
            assert ("gate" in x) == (x["id"] in ("w01_dca", "w04_index_cap25"))
            assert "gate" not in r
            assert {k: v for k, v in x.items() if k != "gate"} == r


def test_v3_weights_and_carry_years():
    for y in range(2019, 2027):
        bots = _mod("config_v3", y).BOTS
        ids = [b["id"] for b in bots]
        assert ("w02_carry_btc" in ids) == (y >= 2020)
        assert sum(b["capital_pct"] for b in bots) <= 0.90 + 1e-9 if y >= 2020 else True
        assert all(not i.startswith(("v04", "v06", "v07", "v08", "v09")) for i in ids)
        if y >= 2020:
            assert abs(sum(b["capital_pct"] for b in bots) - 0.90) < 1e-9


def test_v3_core_params_equal_v2():
    for y in range(2019, 2027):
        v2 = {b["id"]: b for b in _mod("config_v2", y).BOTS}
        for b in _mod("config_v3", y).BOTS:
            old = {"w01_dca": "v01_dca", "w02_carry_btc": "v02_carry_btc", "w03_carry_eth": "v03_carry_eth", "w04_index_cap25": "v05_index_cap25"}[b["id"]]
            for k, v in v2[old].items():
                if k not in ("id", "capital_pct", "differentiator", "gate"):
                    assert b[k] == v, (y, b["id"], k)
