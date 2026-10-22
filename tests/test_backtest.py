"""Pruebas del backtest en frío 2025: arranque exacto, sin red, sin mirar el futuro, universo punto-en-el-tiempo coherente."""
from __future__ import annotations

import json
import sys
import tempfile
import types
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import config_index  # noqa: E402
import config_index_2025  # noqa: E402
import make_universe_2025 as mu  # noqa: E402
from sim.backtest import HistoricFeed, ms, run_backtest, summarize  # noqa: E402
from sim.cloud import config_signature  # noqa: E402
from tests.test_index import SYMS, frames, mini_cfg  # noqa: E402

H = 3_600_000


def _warm_frames(fr, start_h=48):
    """Recorta como lo hace la descarga real: velas desde (inicio − calentamiento) hasta el final."""
    from sim.engine import Engine
    from sim.ledger import Ledger
    cfg = _cfg()
    led = Ledger(Path(tempfile.mkdtemp(prefix="w_")) / "w.db")
    try:
        w = Engine(led, cfg.BOTS, cfg.PORTFOLIO_CAPITAL, cfg.INTERVAL, portfolio_risk=cfg.PORTFOLIO_RISK).max_warmup + 1
    finally:
        led.close()
    return {s: df[df.index >= (start_h - w) * H] for s, df in fr.items()}


def _cfg():
    return types.SimpleNamespace(BOTS=[mini_cfg()], INTERVAL="1h", PORTFOLIO_CAPITAL=10_000.0,
                                 PORTFOLIO_RISK=dict(max_drawdown=None, cooldown_bars=168))


def test_backtest_starts_exactly_at_start_and_ends_at_end():
    out = tempfile.mkdtemp(prefix="bt_")
    fr = frames(144)                                         # horas 0..143 (la 144 ya no entra: fin exclusivo)
    s = run_backtest(_cfg(), dict(id="bt-t", name="t"), out, start="1970-01-03", end="1970-01-07", feed=object(), frames=_warm_frames(fr), log=lambda *_: None)
    assert s["first_ts"] == 48 * H and s["last_ts"] == 143 * H
    assert s["bars"] == 96
    d = json.loads(Path(out, "dashboard.json").read_text())
    assert d["backtest"]["start"] == "1970-01-03" and d["kpis"]["first_ts"] == 48 * H
    assert Path(out, "summary.json").exists() and not list(Path(out).glob("work.db*"))


def test_backtest_refuses_to_start_late():
    out = tempfile.mkdtemp(prefix="bt_")
    fr = {s: df[df.index >= 60 * H] for s, df in frames(144).items()}      # los datos arrancan DESPUÉS del inicio pedido
    try:
        run_backtest(_cfg(), dict(id="bt-t", name="t"), out, start="1970-01-03", end="1970-01-07", feed=object(), frames=fr, log=lambda *_: None)
    except (RuntimeError, ValueError) as e:
        assert "empez" in str(e) or "Historial" in str(e)
    else:
        raise AssertionError("debió negarse a correr con datos que arrancan tarde")


def test_backtest_does_not_see_the_future():
    """El resultado hasta la hora T no cambia si los datos posteriores a T son otros (no hay mirada al futuro)."""
    base = frames(144, seed=3)
    alt = {s: df.copy() for s, df in base.items()}
    for df in alt.values():                                  # reescribe las últimas 24 h con un desplome
        cut = df.index >= 120 * H
        for c in ("open", "high", "low", "close"):
            df.loc[cut, c] = df.loc[cut, c] * 0.5
    eq = []
    for fr in (base, alt):
        out = tempfile.mkdtemp(prefix="bt_")
        run_backtest(_cfg(), dict(id="bt-t", name="t"), out, start="1970-01-03", end="1970-01-07", feed=object(), frames=_warm_frames(fr), log=lambda *_: None)
        d = json.loads(Path(out, "dashboard.json").read_text())
        ts = np.array(d["series"]["ts"]); tot = np.sum([np.array(v) for v in d["series"]["equity"].values()], axis=0)
        eq.append(tot[ts < 120 * H])
    assert len(eq[0]) > 50 and np.allclose(eq[0], eq[1])


def test_historic_feed_drops_open_candle_and_respects_range():
    feed = HistoricFeed(cache_dir=tempfile.mkdtemp(prefix="bf_"), pause=0)
    n = 10
    df = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0, "close_time": 0},
                      index=pd.Index(np.arange(n, dtype="int64") * H, name="ts"))
    feed.fetch_klines = lambda symbol, interval, start_ms=None, end_ms=None: df
    got = feed.closed_range("AAAUSDT", "1h", 2 * H, 8 * H)
    assert list(got.index) == [i * H for i in range(2, 8)]


def test_summarize_sharpe_and_vs_btc_fields():
    out = tempfile.mkdtemp(prefix="bt_")
    s = run_backtest(_cfg(), dict(id="bt-t", name="t"), out, start="1970-01-03", end="1970-01-07", feed=object(), frames=_warm_frames(frames(144)), log=lambda *_: None)
    assert s["btc_roi"] is None and isinstance(s["roi"], float) and s["n_trades"] > 0 and s["bots"][0]["roi"] is not None
    assert s["sharpe"] is None or np.isfinite(s["sharpe"])


def test_config_index_2025_is_consistent_and_different_from_live():
    c = config_index_2025
    assert len(c.TOP50) == 50 and c.TOP25 == c.TOP50[:25] and len(set(c.TOP50)) == 50
    caps = [c.CAPS_USD[s] for s in c.TOP50]
    assert caps == sorted(caps, reverse=True) and caps[0] > 1.8e12            # BTC al 2025-01-01
    assert set(c.SLIPPAGE_BPS) == set(c.TOP50)
    assert not {"USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "PAXGUSDT", "XAUTUSDT"} & set(c.TOP50)
    live = [dict(b) for b in config_index.BOTS]
    assert [b["id"] for b in c.BOTS] == [b["id"] for b in live]
    assert [b["params"] for b in c.BOTS] == [b["params"] for b in live]        # mismos parámetros que en vivo
    assert config_signature(c.BOTS, c.PORTFOLIO_CAPITAL, c.PORTFOLIO_RISK) != config_signature(live, config_index.PORTFOLIO_CAPITAL, config_index.PORTFOLIO_RISK)


def test_universe_rules_are_applied():
    ranked, excluded = mu.build()
    assert ranked and all(r["first_day"] <= "2024-01-01" for r in ranked)
    why = {b: r for b, r, _ in excluded}
    assert "TON" not in {r["base"] for r in ranked}                             # listada en ago-2024: < 365 días
    assert "FTM" in why and "dejó de cotizar" in why["FTM"]
    stored = json.loads((ROOT / "backtest_2025" / "universe_2025.json").read_text())
    assert [r["symbol"] for r in stored["top50"]] == list(config_index_2025.TOP50)   # el config generado = el universo guardado
    assert mu.tier(150e6) == 5 and mu.tier(40e6) == 8 and mu.tier(12e6) == 15 and mu.tier(4e6) == 25 and mu.tier(1e6) == 40


def test_ms_parses_utc_dates():
    assert ms("2025-01-01") == 1735689600000 and ms("2026-01-01") == 1767225600000


def test_holdout_2026_universe_and_cli():
    import config_index_2026 as c26
    import backtest_run
    assert len(c26.TOP50) == 50 and c26.TOP25 == c26.TOP50[:25]
    caps = [c26.CAPS_USD[s] for s in c26.TOP50]
    assert caps == sorted(caps, reverse=True) and 1.7e12 < caps[0] < 1.8e12       # BTC al 2026-01-01
    assert set(c26.SLIPPAGE_BPS) == set(c26.TOP50)
    assert not {"USDCUSDT", "FDUSDUSDT", "USDEUSDT", "XAUTUSDT", "PAXGUSDT", "USD1USDT"} & set(c26.TOP50)
    assert [b["params"] for b in c26.BOTS] == [b["params"] for b in config_index.BOTS]
    stored = json.loads((ROOT / "backtest_2026" / "universe_2025.json").read_text())
    assert [r["symbol"] for r in stored["top50"]] == list(c26.TOP50) and stored["as_of"] == "2026-01-01"
    assert all(r["first_day"] <= "2025-01-01" for r in stored["top50"])             # ≥ 365 días de historial al inicio
    s26 = backtest_run.sims_for("2026")
    assert s26["indexado"][0] == "config_index_2026" and s26["actual"][0] == "config" and s26["dinamico"][0] == "config_active"
    assert s26["actual"][1]["id"] == "bt26-actual" and backtest_run.sims_for("2025")["actual"][1]["id"] == "bt-actual"
