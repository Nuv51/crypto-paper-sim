"""Pestaña Summary: posiciones por activo y familias de estrategia salen cuadradas con el equity de los bots.

Ejecuta:  python -m pytest -q
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from sim.cloud import config_signature, run_step  # noqa: E402
from sim.export import FAMILIES, family_of  # noqa: E402

CAP = config.PORTFOLIO_CAPITAL


@pytest.fixture(scope="module")
def dash():
    with tempfile.TemporaryDirectory() as tmp:
        code, _ = run_step(config.BOTS, config.INTERVAL, CAP, None, tmp, "synthetic", synthetic_advance=24)
        assert code == 0
        return json.loads((Path(tmp) / "dashboard.json").read_text(encoding="utf-8"))


def test_holdings_add_up_to_equity(dash):
    H = dash["holdings"]
    eq = sum(b["equity"] for b in dash["bots"])
    assert H["total"] == pytest.approx(eq, abs=1e-6)
    assert H["invested"] + H["cash"] == pytest.approx(eq, abs=1e-6)
    assert H["invested"] == pytest.approx(sum(a["value"] for a in H["by_asset"]), abs=1e-6)
    for b in dash["bots"]:
        assert b["cash"] + sum(p["value"] for p in b["positions"]) == pytest.approx(b["equity"], abs=1e-6)


def test_holdings_only_real_spot_markets(dash):
    syms = [a["symbol"] for a in dash["holdings"]["by_asset"]]
    assert all("~" not in s and s.endswith("USDT") for s in syms)
    assert syms == sorted(syms, key=lambda s: -next(a["value"] for a in dash["holdings"]["by_asset"] if a["symbol"] == s))
    assert all(a["value"] > 0 and a["bots"] for a in dash["holdings"]["by_asset"])


def test_families_cover_every_bot_once(dash):
    seen = [i for f in dash["families"] for i in f["bots"]]
    assert sorted(seen) == sorted(b["id"] for b in dash["bots"])           # cada bot en una sola familia
    assert all(b["family"] != "otros" for b in dash["bots"])               # ningún bot quedó sin clasificar
    assert sum(f["equity"] for f in dash["families"]) == pytest.approx(sum(b["equity"] for b in dash["bots"]), abs=1e-6)
    assert sum(f["capital"] for f in dash["families"]) == pytest.approx(dash["kpis"]["capital"], abs=1e-6)
    for f in dash["families"]:
        assert f["pnl"] == pytest.approx(f["equity"] - f["capital"], abs=1e-6)


def test_family_rule_and_config_untouched():
    assert family_of("b04_grid") == "rango" and family_of("b10_xrp") == "neutral" and family_of("zzz") == "otros"
    kinds = {k for _key, _name, ks in FAMILIES for k in ks}
    assert {b["id"].split("_", 1)[1] for b in config.BOTS} <= kinds        # un bot nuevo en config obliga a clasificarlo aquí
    assert all("family" not in b for b in config.BOTS)                     # la familia NO viaja en config: no cambia la huella
    assert config_signature(config.BOTS, CAP) == config_signature(json.loads(json.dumps(config.BOTS)), CAP)


def test_page_has_summary_tab_first():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    tabs = re.findall(r'role="tab" data-tab="(\w+)"', html)
    assert tabs[0] == "summary" and tabs[1:] == ["resumen", "pnl", "tx", "riesgo", "tendencias", "bots"]
    assert "summary: panelSummary(" in html
