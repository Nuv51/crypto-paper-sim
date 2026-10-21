"""Pestaña Comparar con N simuladores y registro automático de simuladores (sims.json).

Ejecuta:  python -m pytest -q   (las pruebas de la página necesitan Node; sin Node se omiten)
"""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import config  # noqa: E402
import config_index  # noqa: E402
import make_registry  # noqa: E402
import sim.cloud as cloud  # noqa: E402
from sim.cloud import run_step  # noqa: E402

cloud.fetch_fear_greed = lambda session=None: None
NODE = shutil.which("node")


def _dash(cfg, sim, tmp, name):
    prev = None
    for k in range(2):                                          # dos corridas: así hay varias velas y se puede graficar
        out = tmp / f"{name}{k}"
        code, _ = run_step(cfg.BOTS, cfg.INTERVAL, cfg.PORTFOLIO_CAPITAL, prev, str(out), "synthetic",
                           portfolio_risk=cfg.PORTFOLIO_RISK, sim=sim, synthetic_advance=60)
        assert code == 0
        prev = str(out / "ledger.json")
    return out / "dashboard.json"


def _render(selfp, others):
    r = subprocess.run([NODE, str(ROOT / "tests" / "js" / "compare_harness.js"), str(ROOT / "web" / "index.html"), str(selfp),
                        *map(str, others)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)["html"]


def test_registry_lists_dashboards_in_stable_order_and_skips_synthetic():
    d = Path(tempfile.mkdtemp(prefix="reg_"))
    for name, sid in (("indice", "indice"), ("zeta", "zeta"), ("binance", "actual"), ("activo", "activo"),
                      ("synthetic", "actual"), ("activo-synthetic", "activo"), ("observatorio", None)):
        (d / name / "data").mkdir(parents=True)
        if sid:
            (d / name / "data" / "dashboard.json").write_text(json.dumps({"sim": {"id": sid, "name": f"Simulador {name}"}}))
    (d / "roto" / "data").mkdir(parents=True)
    (d / "roto" / "data" / "dashboard.json").write_text("{no es json")
    reg = make_registry.build(d)
    assert [e["dir"] for e in reg] == ["binance", "activo", "indice", "zeta"]                # prioridad fija, luego alfabético
    assert reg[0]["id"] == "actual" and reg[3]["name"] == "Simulador zeta"


def test_compare_tab_shows_three_simulators_in_one_chart():
    if not NODE:
        return
    tmp = Path(tempfile.mkdtemp(prefix="cmp_"))
    a = _dash(config, dict(id="actual", name="Simulador actual", desc="a"), tmp, "a")
    # (con datos sintéticos el de 15 min arranca en otra fecha; para probar la página basta otro simulador de velas de 1 h)
    b = _dash(config, dict(id="activo", name="Simulador dinámico", desc="b"), tmp, "b")
    c = _dash(config_index, dict(id="indice", name="Simulador indexado", desc="c"), tmp, "c")
    html = _render(a, [b, c])
    assert "Misma prueba, 3 simuladores" in html
    for n in ("Actual", "Dinámico", "Indexado"):
        assert n in html
    assert "Mismo periodo" in html and html.count("<svg") == 1  # una sola gráfica con los tres
    assert "Todavía no hay un periodo en común" not in html
    assert "capitales ficticios son distintos" in html         # indexado tiene 30,000 vs 10,000: avisa que se compare el ROI
    # desde el otro lado también se ven los 3
    assert "Misma prueba, 3 simuladores" in _render(c, [a, b])
    # un simulador futuro se suma solo: cuatro columnas
    d = json.loads(c.read_text())
    d["sim"] = dict(d["sim"], id="nuevo", name="Simulador nuevo")
    dp = tmp / "d.json"
    dp.write_text(json.dumps(d))
    html4 = _render(a, [b, c, dp])
    assert "Misma prueba, 4 simuladores" in html4 and "Nuevo" in html4
    # sin otros simuladores: mensaje de espera, no error
    assert "Aún no hay datos de otros simuladores" in _render(a, [])
