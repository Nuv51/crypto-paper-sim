"""Riesgo automático y atribución: cercanía al límite, freno global y mercado vs bots salen cuadrados en el export.

Ejecuta:  python -m pytest -q
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from sim.cloud import config_signature, run_step  # noqa: E402

CAP = config.PORTFOLIO_CAPITAL
PR = config.PORTFOLIO_RISK


def _run(n_steps: int = 4, advance: int = 24) -> dict:
    """Corre varias veces encadenando el estado guardado, como hace el workflow cada hora."""
    with tempfile.TemporaryDirectory() as tmp:
        state = None
        for k in range(n_steps):
            out = Path(tmp) / f"o{k}"
            code, _ = run_step(config.BOTS, config.INTERVAL, CAP, state, str(out), "synthetic",
                               synthetic_advance=advance, portfolio_risk=PR)
            assert code == 0
            state = str(out / "ledger.json")
        return json.loads((Path(tmp) / f"o{n_steps - 1}" / "dashboard.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def dash():
    return _run()


def test_market_plus_own_equals_the_result(dash):
    k = dash["kpis"]
    assert k["market_pnl"] + k["own_pnl"] == pytest.approx(k["pnl"], abs=1e-3)
    for b in dash["bots"]:
        assert b["market"] + b["own"] == pytest.approx(b["pnl"], abs=1e-3)
    assert sum(b["market"] for b in dash["bots"]) == pytest.approx(k["market_pnl"], abs=1e-3)
    S = dash["series"]
    assert len(S["market_cum"]) == len(S["own_cum"]) == len(S["ts"])
    assert S["market_cum"][-1] + S["own_cum"][-1] == pytest.approx(S["total"][-1] - k["capital"], abs=1e-3)


def test_a_bot_that_never_holds_anything_has_zero_market_effect(dash):
    flat = [b for b in dash["bots"] if not b["positions"] and b["n_trades"] == 0]
    for b in flat:
        assert b["market"] == pytest.approx(0.0, abs=1e-9)


def test_every_bot_exports_how_close_it_is_to_its_limit(dash):
    for b in dash["bots"]:
        r = b["risk_now"]
        assert r["limit"] and r["level"] in ("ok", "watch", "near", "paused", "retired", "halted")
        assert r["used"] == pytest.approx(r["dd"] / r["limit"])
        assert 0 <= r["dd"] < 1 and r["peak"] > 0
    pr = dash["portfolio_risk"]
    assert pr["limit"] == PR["max_drawdown"] and pr["status"] in ("active", "paused")
    assert pr["used"] == pytest.approx(pr["dd"] / pr["limit"])
    json.dumps(dash, allow_nan=False)


def test_global_limit_is_part_of_the_config_signature():
    a = config_signature(config.BOTS, CAP, PR)
    assert a == config_signature(config.BOTS, CAP, dict(PR))
    assert a != config_signature(config.BOTS, CAP, dict(PR, max_drawdown=0.2))
    assert config_signature(config.BOTS, CAP) == config_signature(config.BOTS, CAP, None)


def test_no_rule_waits_for_manual_action():
    assert all(b["risk"].get("action") in ("pause_and_resume", "flag_only") for b in config.BOTS)
    assert [b["id"] for b in config.BOTS if b["risk"]["action"] == "flag_only"] == ["b03_dca"]
    assert all(b["risk"].get("max_strikes") == 3 for b in config.BOTS if b["risk"]["action"] == "pause_and_resume")
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert "revisión manual" not in html.lower()
