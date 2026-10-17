"""Pestaña Summary: posiciones por activo y familias de estrategia salen cuadradas con el equity de los bots.

Ejecuta:  python -m pytest -q
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from sim.cloud import benchmarks_from_feed, config_signature, run_step  # noqa: E402
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
    kinds = {k for _key, _name, ks, _desc in FAMILIES for k in ks}
    assert {b["id"].split("_", 1)[1] for b in config.BOTS} <= kinds        # un bot nuevo en config obliga a clasificarlo aquí
    assert all("family" not in b for b in config.BOTS)                     # la familia NO viaja en config: no cambia la huella
    assert config_signature(config.BOTS, CAP) == config_signature(json.loads(json.dumps(config.BOTS)), CAP)


def test_page_has_summary_tab_first():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    tabs = re.findall(r'role="tab" data-tab="(\w+)"', html)
    assert tabs[0] == "summary" and tabs[1:] == ["resumen", "pnl", "tx", "riesgo", "tendencias", "bots"]
    assert "summary: panelSummary(" in html


class FakeFeed:
    """Velas de mercado inventadas con la misma interfaz que BinanceFeed.latest_closed (solo para la prueba)."""
    pause = 0

    def latest_closed(self, symbol, interval="1h", n=600):
        step = {"1h": 3_600_000, "1d": 86_400_000}[interval]
        end = (1_800_000_000_000 // step) * step - step
        base = 80_000.0 if symbol == "BTCUSDT" else 2_500.0
        idx = pd.Index([end - step * (n - 1 - i) for i in range(n)], dtype="int64", name="ts")
        return pd.DataFrame({"close": [base * (1 + 0.001 * i) for i in range(n)]}, index=idx)


def test_benchmarks_cover_the_periods_and_reach_now():
    B = benchmarks_from_feed(FakeFeed())
    assert set(B) == {"BTCUSDT", "ETHUSDT", "MARKET"}
    for sym, b in B.items():
        assert len(b["h"]["ts"]) == 768 and len(b["h"]["close"]) == 768     # >= 30 días en horas
        assert len(b["d"]["ts"]) == 366                                      # 365 días + el último cierre horario
        assert b["d"]["ts"] == sorted(b["d"]["ts"]) and len(set(b["d"]["ts"])) == len(b["d"]["ts"])
        assert b["d"]["ts"][-1] == b["h"]["ts"][-1] and b["d"]["close"][-1] == b["h"]["close"][-1]


def test_benchmarks_are_optional_and_never_raise():
    class Broken:
        pause = 0

        def latest_closed(self, *a, **k):
            raise RuntimeError("sin red")

    assert benchmarks_from_feed(Broken()) is None
    assert benchmarks_from_feed(object()) is None                  # feed sin latest_closed (el sintético)


def test_dashboard_includes_benchmarks_only_when_given(dash):
    assert "benchmarks" not in dash                                # corrida sintética: no hay historia real que mostrar
    from sim import metrics
    from sim.export import build_dashboard
    from sim.ledger import Ledger
    with tempfile.TemporaryDirectory() as tmp:
        code, _ = run_step(config.BOTS, config.INTERVAL, CAP, None, tmp, "synthetic", synthetic_advance=24)
        led = Ledger(Path(tmp) / "x.db")
        led.restore(json.loads((Path(tmp) / "ledger.json").read_text(encoding="utf-8")))
        out = build_dashboard(metrics.load_all(led.con), 1, benchmarks=benchmarks_from_feed(FakeFeed()))
        led.close()
    assert out["benchmarks"]["BTCUSDT"]["d"]["close"][0] == pytest.approx(80_000.0)
    json.dumps(out, allow_nan=False)                               # JSON estricto
    assert all(f["desc"] for f in out["families"])


def test_market_index_is_a_cap_weighted_basket_and_is_optional():
    from sim.cloud import MARKET_BASKET
    B = benchmarks_from_feed(FakeFeed())["MARKET"]
    assert len(B["h"]["ts"]) == 768 and B["d"]["ts"][-1] == B["h"]["ts"][-1]
    # valor de la canasta en la primera vela horaria = suma(suministro x precio) en miles de millones
    ref = FakeFeed()
    first = sum(MARKET_BASKET[s] * float(ref.latest_closed(s, "1h", 768)["close"].iloc[0]) for s in MARKET_BASKET) / 1e9
    assert B["h"]["close"][0] == pytest.approx(first, rel=1e-4)

    class NoTron(FakeFeed):                                      # si falla una moneda de la canasta solo se omite el índice
        def latest_closed(self, symbol, interval="1h", n=600):
            if symbol == "TRXUSDT":
                raise RuntimeError("sin red")
            return super().latest_closed(symbol, interval, n)
    B2 = benchmarks_from_feed(NoTron())
    assert set(B2) == {"BTCUSDT", "ETHUSDT"}


def test_fear_greed_parser_and_graceful_failure():
    from sim.data import fetch_fear_greed, parse_fear_greed
    rows = [{"value": str(40 - i), "value_classification": "Fear", "timestamp": str(1_800_000_000 - i * 86400)} for i in range(31)]
    g = parse_fear_greed({"data": rows})
    assert g["value"] == 40 and g["label"] == "Miedo" and g["yesterday"]["value"] == 39
    assert g["week"]["value"] == 33 and g["month"]["value"] == 10 and g["ts"] == 1_800_000_000_000

    class Boom:
        def get(self, *a, **k):
            raise RuntimeError("sin red")
    assert fetch_fear_greed(Boom()) is None


def test_family_series_add_up_to_the_portfolio(dash):
    SF, S = dash["series"]["family"], dash["series"]
    assert set(SF) == {f["key"] for f in dash["families"]}
    n = len(S["total"])
    for k in range(n):
        assert sum(SF[f]["equity"][k] for f in SF) == pytest.approx(S["total"][k], abs=1e-3)
    for f in dash["families"]:
        assert SF[f["key"]]["capital"] == pytest.approx(f["capital"])
        assert len(SF[f["key"]]["drawdown"]) == n and max(SF[f["key"]]["drawdown"]) <= 1e-9


def test_page_charts_by_strategy_and_has_fear_greed_gauge():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert html.count("famLines(d,") >= 3                           # Resumen, P&L y Riesgo
    assert "fngCard(d)" in html and "MARKET" in html
