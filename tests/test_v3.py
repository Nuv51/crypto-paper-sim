"""V3: filtro de tendencia (SMA 200 de BTC) sin mirar al futuro, robusto a huecos; el índice y el DCA con filtro liquidan al apagarse y
vuelven a comprar al encenderse (el índice conserva sus suministros fijados el día 0)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim.bots import IndexBot  # noqa: E402
from sim.engine import Engine  # noqa: E402
from sim.gates import btc_sma_gate  # noqa: E402
from sim.ledger import Ledger  # noqa: E402
from tests.test_index import CAPS, SYMS, frames, mini_cfg  # noqa: E402

H = 3_600_000
D = 24


def _path_days():
    """100→200 (días 0-230), cae a 90 (230-270), sube a 250 (270-330)."""
    return np.r_[np.linspace(100, 200, 230 * D), np.linspace(200, 90, 40 * D), np.linspace(90, 250, 60 * D)]


def _btc(path):
    o = np.concatenate([[path[0]], path[:-1]])
    return pd.DataFrame({"open": o, "high": np.maximum(o, path) * 1.0002, "low": np.minimum(o, path) * 0.9998, "close": path,
                         "volume": np.full(len(path), 1000.0)}, index=pd.Index(np.arange(len(path), dtype="int64") * H, name="ts"))


def test_sma_gate_needs_full_history_follows_trend_and_never_peeks_ahead():
    df = _btc(_path_days())
    ts, cl = df.index.to_numpy(np.int64), df.close.to_numpy(float)
    g = btc_sma_gate(cl, ts, 200)
    assert not g[: 200 * D].any()                                    # sin 200 días completos: apagado
    assert g[210 * D] and g[225 * D]                                 # tendencia alcista: encendido
    assert not g[268 * D]                                            # tras la caída: apagado
    assert g[-1]                                                     # recuperación: otra vez encendido
    cut = 240 * D                                                    # el estado hasta `cut` no cambia si cambia el futuro
    alt = cl.copy(); alt[cut:] = alt[cut:][::-1] * 3
    assert np.array_equal(g[:cut], btc_sma_gate(alt, ts, 200)[:cut])
    first_day = [i for i in range(1, len(ts)) if (ts[i] // H) % 24 == 0]
    flips = [i for i in range(1, len(g)) if g[i] != g[i - 1]]
    assert all(i in first_day for i in flips)                        # solo cambia en la primera vela del día UTC


def test_sma_gate_is_robust_to_data_gaps():
    df = _btc(_path_days())
    ts, cl = df.index.to_numpy(np.int64), df.close.to_numpy(float)
    full = btc_sma_gate(cl, ts, 200)
    keep = np.ones(len(ts), dtype=bool); keep[250 * D + 3: 250 * D + 9] = False       # 6 h sin datos
    gap = btc_sma_gate(cl[keep], ts[keep], 200)
    assert np.array_equal(gap, full[keep])


def _run(cfg, fr, gate_series):
    led = Ledger(Path(tempfile.mkdtemp(prefix="v3_")) / "t.db")
    eng = Engine(led, [cfg], 10_000.0, "1h", portfolio_risk=dict(max_drawdown=None, cooldown_bars=168))
    eng.replay(fr, progress=None, gate_series=gate_series)
    return eng, led


def test_engine_requires_external_series_for_sma_gate():
    cfg = mini_cfg(rebalance_hours=720); cfg["gate"] = dict(type="btc_sma", symbol="BTCUSDT", sma_days=200)
    fr = frames(24 * 30); fr["BTCUSDT"] = _btc(np.linspace(100, 110, 24 * 30))
    led = Ledger(Path(tempfile.mkdtemp(prefix="v3_")) / "t.db")
    eng = Engine(led, [cfg], 10_000.0, "1h", portfolio_risk=dict(max_drawdown=None, cooldown_bars=168))
    try:
        eng.replay(fr, progress=None)
    except ValueError as e:
        assert "gate_series" in str(e)
    else:
        raise AssertionError("debió exigir la serie larga del interruptor")


def test_gated_index_liquidates_when_off_and_rebuys_when_on_keeping_supply():
    btc = _btc(_path_days()); n = len(btc)
    fr = frames(n); fr["BTCUSDT"] = btc
    cfg = mini_cfg(rebalance_hours=24 * 90); cfg["gate"] = dict(type="btc_sma", symbol="BTCUSDT", sma_days=200)
    eng, led = _run(cfg, fr, {"BTCUSDT": btc})
    tr = pd.read_sql_query("SELECT ts, side, reason, symbol FROM trades ORDER BY ts", led.con)
    ev = pd.read_sql_query("SELECT ts, message FROM events ORDER BY ts", led.con)
    assert tr.ts.min() >= 200 * D * H                                # no compra antes de que el filtro tenga 200 días
    off = ev[ev.message.str.contains("APAGADO")].ts.min(); on2 = ev[ev.message.str.contains("ENCENDIDO")].ts.max()
    assert off == off and on2 > off
    assert (tr[(tr.reason == "risk_halt")].shape[0]) >= 1            # al apagarse vende todo
    after_off = tr[(tr.ts > off) & (tr.ts < on2)]
    assert (after_off.side == "buy").sum() == 0                      # mientras está apagado no compra
    assert (tr[tr.ts > on2].side == "buy").sum() > 0                 # al encenderse vuelve a comprar el índice
    bot = eng.runtimes["i99_index_t"].bot
    first_px = {s: float(fr[s].close.loc[tr.ts.min() - H]) for s in SYMS} if (tr.ts.min() - H) in fr[SYMS[0]].index else None
    assert bot.st["supply"] and set(bot.st["supply"]) == set(SYMS)
    if first_px:                                                     # suministro = capitalización inicial / precio del día de la primera compra
        for s in SYMS:
            assert abs(bot.st["supply"][s] * first_px[s] / CAPS[s] - 1) < 0.02


def test_index_reset_keeps_supply_and_restarts():
    bot = IndexBot(dict(mini_cfg(), capital=10_000.0), 3_600_000)
    bot.st.update(supply={s: 1.0 for s in SYMS}, started_ts=123, last_rb_ts=99, phase="buy", n_rebalances=3)
    bot.reset()
    assert bot.st["supply"] == {s: 1.0 for s in SYMS} and bot.st["started_ts"] == 0 and bot.st["phase"] == "idle" and bot.st["n_rebalances"] == 0


def test_gated_dca_buys_only_while_trend_is_up_and_liquidates_when_off():
    btc = _btc(_path_days()); fr = {"BTCUSDT": btc}
    cfg = dict(id="t_dca", kind="dca", name="t", exchange="binance", symbols=["BTCUSDT"], capital_pct=1.0, risk_level="bajo", slippage_bps=2,
               params=dict(interval_hours=24 * 7, contribution_pct=0.03), risk=dict(max_drawdown=0.9, action="flag_only"),
               gate=dict(type="btc_sma", symbol="BTCUSDT", sma_days=200))
    eng, led = _run(cfg, fr, {"BTCUSDT": btc})
    tr = pd.read_sql_query("SELECT ts, side, reason FROM trades ORDER BY ts", led.con)
    ev = pd.read_sql_query("SELECT ts, message FROM events", led.con)
    off = ev[ev.message.str.contains("APAGADO")].ts.min(); on2 = ev[ev.message.str.contains("ENCENDIDO")].ts.max()
    buys = tr[(tr.side == "buy") & (tr.reason == "dca")]
    assert buys.ts.min() >= 200 * D * H and ((buys.ts > off + 2 * H) & (buys.ts < on2)).sum() == 0
    assert (tr.reason == "risk_halt").sum() >= 1 and (buys.ts > on2).sum() > 0
