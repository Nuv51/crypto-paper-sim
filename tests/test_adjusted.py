"""Simulador AJUSTADO V1 (config_adjusted.py): configuración, efectivo explícito, corrida sintética, registro y botones del tablero.

Ejecuta:  python -m pytest -q   (las pruebas de la página necesitan Node; sin Node se omiten)
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import config  # noqa: E402
import config_adjusted as adj  # noqa: E402
import config_index  # noqa: E402
import config_v3ref_2026 as v3ref  # noqa: E402
import make_registry  # noqa: E402
import sim.cloud as cloud  # noqa: E402
from cloud_step import SIMS  # noqa: E402
from sim.bots import BOT_CLASSES  # noqa: E402
from sim.cloud import config_signature, run_step  # noqa: E402
from sim.export import family_of  # noqa: E402

cloud.fetch_fear_greed = lambda session=None: None
NODE = shutil.which("node")
IDENT = {k: v for k, v in SIMS["config_adjusted"].items() if k in ("id", "name", "other", "desc")}


def _step(tmp, name, prev=None, advance=120):
    return run_step(adj.BOTS, adj.INTERVAL, adj.PORTFOLIO_CAPITAL, prev, str(tmp / name), "synthetic", synthetic_advance=advance,
                    portfolio_risk=adj.PORTFOLIO_RISK, sim=IDENT, window=400, keep_bars=400)


def test_config_is_the_pre_registered_mix():
    w = {b["id"]: b["capital_pct"] for b in adj.BOTS}
    assert w == {"a01_dca": 0.20, "a02_index_cap25": 0.30, "a03_carry_btc": 0.25, "a04_carry_eth": 0.15, "a05_cash": 0.10}
    assert sum(w.values()) == pytest.approx(1.0) and adj.PORTFOLIO_CAPITAL == 10_000.0 and adj.INTERVAL == "1h"
    assert adj.PORTFOLIO_RISK["max_drawdown"] is None                                  # sin freno global, como en V3
    assert all(b["kind"] in BOT_CLASSES for b in adj.BOTS) and all("gate" not in b for b in adj.BOTS)   # sin filtro de tendencia
    ids = [b["id"] for b in adj.BOTS]
    assert len(ids) == len(set(ids)) and not set(ids) & {b["id"] for b in config.BOTS}
    assert all(family_of(i) != "otros" for i in ids)
    assert SIMS["config_adjusted"]["name"] == "Simulador Ajustado V1" and SIMS["config_adjusted"]["id"] == "ajustado"


def test_parameters_equal_the_backtested_v3_ref():
    by = {b["id"]: b for b in v3ref.BOTS}
    for a, v in (("a01_dca", "w01_dca"), ("a02_index_cap25", "w04_index_cap25"), ("a03_carry_btc", "w02_carry_btc"), ("a04_carry_eth", "w03_carry_eth")):
        b = next(x for x in adj.BOTS if x["id"] == a)
        for k in ("kind", "exchange", "params", "risk", "capital_pct", "slippage_bps"):
            assert b[k] == by[v][k], (a, k)


def test_index_universe_is_the_frozen_live_top25():
    b = next(x for x in adj.BOTS if x["kind"] == "index")
    assert b["symbols"] == config_index.TOP25 and len(b["symbols"]) == 25
    assert set(b["caps_usd"]) == set(b["symbols"]) == set(b["slippage_map_bps"])
    assert b["params"]["rebalance_hours"] == 90 * 24                                  # trimestral, no mensual


def test_other_simulators_are_untouched():
    assert config_signature(config.BOTS, config.PORTFOLIO_CAPITAL, config.PORTFOLIO_RISK) == "e81e4a30f9318b5a"
    assert config_signature(adj.BOTS, adj.PORTFOLIO_CAPITAL, adj.PORTFOLIO_RISK) != \
        config_signature(config_index.BOTS, config_index.PORTFOLIO_CAPITAL, config_index.PORTFOLIO_RISK)


def test_synthetic_run_counts_cash_in_equity_and_resumes():
    tmp = Path(tempfile.mkdtemp(prefix="adj_"))
    code, _ = _step(tmp, "o0", None, 1)
    assert code == 0
    code, st = _step(tmp, "o1", str(tmp / "o0" / "ledger.json"), 150)
    assert code == 0
    code, st2 = _step(tmp, "o2", str(tmp / "o1" / "ledger.json"), 100)
    assert code == 0 and "100" in st2["message"]                                      # retoma el estado y procesa las barras nuevas
    d = json.loads((tmp / "o2" / "dashboard.json").read_text())
    K = d["kpis"]
    assert d["sim"]["id"] == "ajustado" and K["capital"] == pytest.approx(10_000.0) and K["reserve"] == pytest.approx(0.0)
    bots = {b["id"]: b for b in d["bots"]}
    assert bots["a05_cash"]["equity"] == pytest.approx(1_000.0) and bots["a05_cash"]["family"] == "efectivo"
    assert not [t for t in d["trades"] if t["bot"] == "a05_cash"] if isinstance(d.get("trades"), list) and d["trades"] and isinstance(d["trades"][0], dict) else True
    assert K["equity"] == pytest.approx(sum(b["equity"] for b in d["bots"]))          # el efectivo cuenta en el total
    assert {f["key"] for f in d["families"]} >= {"acumulacion", "indice", "neutral", "efectivo"}


def test_registry_puts_adjusted_after_the_three_existing_ones():
    d = Path(tempfile.mkdtemp(prefix="reg_"))
    for name, sid in (("ajustado", "ajustado"), ("indice", "indice"), ("binance", "actual"), ("activo", "activo")):
        (d / name / "data").mkdir(parents=True)
        (d / name / "data" / "dashboard.json").write_text(json.dumps({"sim": {"id": sid, "name": f"Simulador {name}"}}))
    assert [e["dir"] for e in make_registry.build(d)] == ["binance", "activo", "indice", "ajustado"]


def _nav(reg, my_id, my_dir):
    p = Path(tempfile.mkdtemp(prefix="nav_")) / "reg.json"
    p.write_text(json.dumps(reg))
    r = subprocess.run([NODE, str(ROOT / "tests" / "js" / "nav_harness.js"), str(ROOT / "web" / "index.html"), str(p), my_id, my_dir],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)["html"]


def test_dashboard_has_buttons_to_switch_simulator():
    if not NODE:
        return
    reg = [dict(dir="binance", id="actual", name="Simulador actual"), dict(dir="activo", id="activo", name="Simulador dinámico"),
           dict(dir="indice", id="indice", name="Simulador indexado"), dict(dir="ajustado", id="ajustado", name="Simulador Ajustado V1")]
    html = _nav(reg, "ajustado", "ajustado")
    for label, d in (("Actual", "binance"), ("Dinámico", "activo"), ("Indexado", "indice"), ("Ajustado V1", "ajustado")):
        assert f'href="../{d}/"' in html and f">{label}</a>" in html
    assert html.count('aria-current="page"') == 1 and 'data-dir="ajustado" aria-current="page"' in html    # solo el actual va resaltado
    # el simulador actual (carpeta binance, id actual) se resalta aunque el registro llegue sin nombres
    html2 = _nav([dict(dir=k, id=k) for k in ("binance", "activo", "indice", "ajustado")], "actual", "binance")
    assert 'data-dir="binance" aria-current="page"' in html2 and ">Ajustado V1</a>" in html2 and html2.count('aria-current="page"') == 1


def test_compare_tab_includes_adjusted_with_the_other_three():
    if not NODE:
        return
    tmp = Path(tempfile.mkdtemp(prefix="cmpadj_"))

    def dash(cfg, ident, name, ident_kw=None):
        prev = None
        for k in range(2):
            out = tmp / f"{name}{k}"
            code, _ = run_step(cfg.BOTS, cfg.INTERVAL, cfg.PORTFOLIO_CAPITAL, prev, str(out), "synthetic", portfolio_risk=cfg.PORTFOLIO_RISK,
                               sim=ident, synthetic_advance=60)
            assert code == 0
            prev = str(out / "ledger.json")
        return out / "dashboard.json"

    me = dash(adj, IDENT, "me")
    a = dash(config, dict(id="actual", name="Simulador actual", desc="a"), "a")
    c = dash(config_index, dict(id="indice", name="Simulador indexado", desc="c"), "c")
    d = dash(config, dict(id="activo", name="Simulador dinámico", desc="d"), "d")
    r = subprocess.run([NODE, str(ROOT / "tests" / "js" / "compare_harness.js"), str(ROOT / "web" / "index.html"), str(me), str(a), str(d), str(c)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    html = json.loads(r.stdout)["html"]
    assert "Misma prueba, 4 simuladores" in html and "Ajustado V1" in html and "Efectivo" in html
    assert html.count("<svg") == 1 and "Mismo periodo" in html
