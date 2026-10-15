"""Pruebas del modo nube: snapshot del estado, corridas por tandas = corrida continua, fallas de red y JSON del tablero.

Ejecuta:  python -m pytest -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from sim import metrics  # noqa: E402
from sim.cloud import run_step  # noqa: E402
from sim.data import SyntheticFeed  # noqa: E402
from sim.engine import Engine  # noqa: E402
from sim.ledger import Ledger  # noqa: E402

CAP = config.PORTFOLIO_CAPITAL


def step(tmp, name, state=None, advance=24, source="synthetic", feed=None):
    return run_step(config.BOTS, config.INTERVAL, CAP, state, str(tmp / name), source, feed=feed,
                    synthetic_advance=advance)


def load_snapshot(path, tmp, name):
    led = Ledger(tmp / name)
    led.restore(json.loads(Path(path).read_text(encoding="utf-8")))
    return led


def test_snapshot_roundtrip(tmp_path):
    code, _ = step(tmp_path, "r1")
    assert code == 0
    snap = json.loads((tmp_path / "r1" / "ledger.json").read_text(encoding="utf-8"))
    led = load_snapshot(tmp_path / "r1" / "ledger.json", tmp_path, "x.db")
    assert json.loads(json.dumps(led.dump())) == snap
    led.close()


def test_batched_runs_match_one_bar_at_a_time(tmp_path):
    """Correr cada 24 velas (sesiones nuevas, estado en JSON) debe dar lo mismo que procesar vela por vela."""
    state = None
    for i, adv in enumerate([24, 24, 24, 24, 24]):          # la 1ª corrida procesa 1 vela y luego 24 por corrida
        code, st = step(tmp_path, f"r{i}", state, advance=adv)
        assert code == 0, st
        state = str(tmp_path / f"r{i}" / "ledger.json")
    assert st["resumed"] and st["bars_processed"] == 24

    led = load_snapshot(state, tmp_path, "batched.db")
    A = metrics.load_all(led.con)

    feed = SyntheticFeed(seed=7)
    syms = sorted({s for b in config.BOTS for s in b["symbols"]})
    full = {s: feed.history(s, "1h", 60) for s in syms}
    common = sorted(set.intersection(*[set(int(t) for t in f.index) for f in full.values()]))
    ref_led = Ledger(tmp_path / "ref.db")
    eng = Engine(ref_led, config.BOTS, CAP, "1h")
    for t in common[800: 800 + 1 + 24 * 4]:
        eng.process_new({s: f[f.index <= t].tail(700) for s, f in full.items()})
    B = metrics.load_all(ref_led.con)

    assert len(A["equity"]) == len(B["equity"]) > 400
    m = A["equity"].merge(B["equity"], on=["ts", "bot_id"], suffixes=("_a", "_b"))
    assert len(m) == len(A["equity"])
    assert np.allclose(m.equity_a, m.equity_b, rtol=1e-6, atol=1e-6)
    key = ["ts", "bot_id", "symbol", "side", "kind"]
    assert A["trades"][key].reset_index(drop=True).equals(B["trades"][key].reset_index(drop=True))
    assert np.allclose(A["trades"].price, B["trades"].price, rtol=1e-6)
    led.close()
    ref_led.close()


def test_rerun_without_new_bars_is_idempotent(tmp_path):
    step(tmp_path, "a")
    step(tmp_path, "b", str(tmp_path / "a" / "ledger.json"), advance=24)
    code, st = step(tmp_path, "c", str(tmp_path / "b" / "ledger.json"), advance=0)      # misma vela otra vez
    assert code == 0 and st["bars_processed"] == 0
    assert (tmp_path / "b" / "ledger.json").read_text() == (tmp_path / "c" / "ledger.json").read_text()


class _DownFeed:
    label = "Binance (mercado real, API pública)"
    pause = 0

    def latest_closed(self, *a, **k):
        raise ConnectionError("proxy rechazó la conexión")


def test_network_failure_leaves_state_untouched(tmp_path):
    code, st = step(tmp_path, "down", None, source="binance", feed=_DownFeed())
    assert code == 2 and not st["ok"] and "No pude leer velas" in st["message"]
    assert not (tmp_path / "down" / "ledger.json").exists()                 # no se publica estado a medias
    assert json.loads((tmp_path / "down" / "status.json").read_text())["ok"] is False


def test_sources_are_never_mixed(tmp_path):
    step(tmp_path, "syn")                                                   # estado SINTÉTICO
    code, st = step(tmp_path, "mix", str(tmp_path / "syn" / "ledger.json"), source="binance", feed=_DownFeed())
    assert code == 1 and "no se mezclan fuentes" in st["message"]


def test_dashboard_json_is_strict_and_complete(tmp_path):
    state = None
    for i in range(4):
        code, _ = step(tmp_path, f"d{i}", state)
        state = str(tmp_path / f"d{i}" / "ledger.json")
    txt = (tmp_path / "d3" / "dashboard.json").read_text(encoding="utf-8")

    def boom(c):
        raise AssertionError(f"constante no JSON: {c}")
    d = json.loads(txt, parse_constant=boom)                                 # sin NaN/Infinity

    n = len(d["series"]["ts"])
    assert n > 50 and d["series"]["ts"] == sorted(d["series"]["ts"])
    assert all(len(v) == n for v in d["series"]["equity"].values())
    assert len(d["series"]["total"]) == n and len(d["series"]["drawdown_total"]) == n
    assert {b["id"] for b in d["bots"]} == {b["id"] for b in config.BOTS}
    assert d["synthetic"] is True and d["kpis"]["reserve"] == pytest.approx(CAP - d["kpis"]["capital"])
    syms = sorted({s for b in config.BOTS for s in b["symbols"]})
    assert sorted(d["prices"]) == syms
    assert sorted(d["forecasts"]) == syms, "faltan estimaciones de tendencia"
    f = d["forecasts"][syms[0]]["h"]["24"]
    assert len(f["center"]) == 25 and all(lo <= c <= hi for lo, c, hi in zip(f["lo2"], f["center"], f["hi2"]))
    assert d["trades"]["cols"][0] == "ts" and d["trades"]["total"] >= len(d["trades"]["rows"])
