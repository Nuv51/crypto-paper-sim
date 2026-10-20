"""Pruebas del simulador DINÁMICO (velas de 15 min, config_active.py) y de que el actual no cambió.

Ejecuta:  python -m pytest -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import config_active as dyn  # noqa: E402
from cloud_step import SIMS  # noqa: E402
from sim.bots import CarryBot, MLBot  # noqa: E402
from sim.cloud import config_signature, run_step  # noqa: E402
from sim.data import INTERVAL_MS, SyntheticFeed  # noqa: E402
from sim.export import family_of  # noqa: E402
from sim.ledger import Ledger  # noqa: E402

DAY_BARS = 96


def step(tmp, name, state=None, advance=96):
    return run_step(dyn.BOTS, dyn.INTERVAL, dyn.PORTFOLIO_CAPITAL, state, str(tmp / name), "synthetic",
                    synthetic_advance=advance, portfolio_risk=dyn.PORTFOLIO_RISK, sim=SIMS["config_active"])


def test_current_simulator_config_is_untouched():
    # huella del simulador que ya está corriendo en producción: si cambia, el estado guardado se rechaza (y se perdería la prueba)
    assert config_signature(config.BOTS, config.PORTFOLIO_CAPITAL, config.PORTFOLIO_RISK) == "e81e4a30f9318b5a"
    assert config.INTERVAL == "1h" and config.PORTFOLIO_RISK["cooldown_bars"] == 168


def test_dynamic_config_is_sane():
    ids = [b["id"] for b in dyn.BOTS]
    assert len(ids) == len(set(ids)) and not set(ids) & {b["id"] for b in config.BOTS}
    assert sum(b["capital_pct"] for b in dyn.BOTS) == pytest.approx(1.0)
    assert dyn.INTERVAL == "15m" and dyn.PORTFOLIO_CAPITAL == config.PORTFOLIO_CAPITAL
    assert all(family_of(i) != "otros" for i in ids)                           # cada bot cae en una familia
    feed = SyntheticFeed(seed=1)
    for b in dyn.BOTS:
        for s in b["symbols"]:
            if "~" in s and "RAIL" not in s and "PERP" not in s:
                raise AssertionError(f"fuente especial desconocida: {s}")
            if "~" not in s:
                assert not feed.history(s, "15m", 2).empty, f"{s} sin velas en el feed sintético: {b['id']}"
    assert config_signature(dyn.BOTS, dyn.PORTFOLIO_CAPITAL, dyn.PORTFOLIO_RISK) != \
        config_signature(config.BOTS, config.PORTFOLIO_CAPITAL, config.PORTFOLIO_RISK)


def test_time_based_rules_last_the_same_in_real_time():
    assert dyn.PORTFOLIO_RISK["cooldown_bars"] * INTERVAL_MS["15m"] == config.PORTFOLIO_RISK["cooldown_bars"] * INTERVAL_MS["1h"]
    for b in dyn.BOTS:
        rk = b["risk"]
        if rk.get("action") == "pause_and_resume":
            assert rk["cooldown_bars"] == 7 * DAY_BARS and rk["strike_window_bars"] == 30 * DAY_BARS
    dca = next(b for b in dyn.BOTS if b["kind"] == "dca")
    n = len(dca["symbols"])
    assert dca["capital_pct"] * dyn.PORTFOLIO_CAPITAL * dca["params"]["contribution_pct"] / n >= 5.0 * 1.5   # sobre el mínimo de orden


def test_bar_dependent_lookbacks_scale_with_bar_size():
    spec = dict(id="x_carry", kind="carry", name="x", exchange="kucoin", symbols=["BTCUSDT", "BTCUSDT~PERP"], capital=1000.0)
    assert CarryBot(spec, INTERVAL_MS["1h"])._warmup() == 60                    # idéntico al simulador actual
    assert CarryBot(spec, INTERVAL_MS["15m"])._warmup() == 240                  # las mismas 60 h en barras de 15 min
    ml = MLBot(dict(spec, id="x_ml", kind="ml", symbols=["BTCUSDT"], params=dict(horizon=4)), INTERVAL_MS["15m"])
    assert "1 h" in ml.strategy_label
    assert "6 h" in MLBot(dict(spec, id="y_ml", kind="ml", symbols=["BTCUSDT"]), INTERVAL_MS["1h"]).strategy_label


def test_dynamic_runs_resumes_and_labels_itself(tmp_path):
    code, st = step(tmp_path, "a")
    assert code == 0, st
    code, st = step(tmp_path, "b", tmp_path / "a" / "ledger.json")
    assert code == 0 and st["resumed"] and st["bars_processed"] == 96
    code, st = step(tmp_path, "c", tmp_path / "b" / "ledger.json")
    assert code == 0
    d = json.loads((tmp_path / "c" / "dashboard.json").read_text(encoding="utf-8"))
    assert d["sim"]["id"] == "activo" and d["sim"]["other"] == "binance" and d["interval"] == "15m" and d["bar_ms"] == 900_000
    assert len(d["bots"]) == len(dyn.BOTS) and all(b["family"] != "otros" for b in d["bots"])
    dca = next(b for b in d["bots"] if b["id"] == "d04_dca")
    assert dca["n_trades"] >= 3, "el DCA debe poder comprar (cada orden sobre el mínimo)"
    assert sum(b["equity"] for b in d["bots"]) == pytest.approx(d["kpis"]["equity"], abs=1e-3)
    # un cambio de configuración se rechaza (no se mezclan reglas)
    changed = [dict(b) for b in dyn.BOTS]
    changed[0] = dict(changed[0], params=dict(changed[0]["params"], min_apr=0.5))
    code, st = run_step(changed, dyn.INTERVAL, dyn.PORTFOLIO_CAPITAL, str(tmp_path / "c" / "ledger.json"), str(tmp_path / "d"),
                        "synthetic", portfolio_risk=dyn.PORTFOLIO_RISK)
    assert code == 1 and "configuración" in st["message"]


def test_forecast_horizons_are_hours_not_bars(tmp_path):
    for i, name in enumerate("abcd"):                                        # ~3 días: suficiente historia para estimar
        code, _ = step(tmp_path, name, None if i == 0 else tmp_path / "abcd"[i - 1] / "ledger.json")
        assert code == 0
    d = json.loads((tmp_path / "d" / "dashboard.json").read_text(encoding="utf-8"))
    assert d["forecasts"], "con 15 min debe haber historia suficiente (7 días = 672 barras de lookback, mínimo la mitad)"
    h = next(iter(d["forecasts"].values()))["h"]
    assert set(h) == {"24", "72"}
    assert len(h["24"]["center"]) >= 96 and len(h["72"]["center"]) >= 288      # horas × 4 barras por hora


def _mk_ledger(tmp_path, bar_ms, n_bars):
    led = Ledger(tmp_path / "c.db")
    start = 1_700_000_000_000 - (1_700_000_000_000 % 3_600_000) + 3_600_000 - bar_ms      # primera barra: cierra en hora exacta
    for k in range(n_bars):
        ts = start + k * bar_ms
        for bid, mult in (("a", 1.0), ("b", 2.0)):
            led.add_equity([(ts, bid, 100 + k * mult, 10.0, 0.0, 0.0, 0.0)])
            led.add_attrib([(ts, bid, 0.5 * mult)])
    led.commit()
    return led, start


def test_compaction_keeps_recent_hourly_close_and_conserves_attribution(tmp_path):
    bar = INTERVAL_MS["15m"]
    led, start = _mk_ledger(tmp_path, bar, 6 * DAY_BARS)                      # 6 días de 15 min
    last = start + (6 * DAY_BARS - 1) * bar
    tot_before = led.con.execute("SELECT SUM(market) FROM attrib").fetchone()[0]
    n_before = led.con.execute("SELECT COUNT(*) FROM equity").fetchone()[0]
    dropped = led.compact_equity(last, bar)
    n_after = led.con.execute("SELECT COUNT(*) FROM equity").fetchone()[0]
    assert dropped > 0 and n_after == n_before - dropped < n_before
    assert led.con.execute("SELECT SUM(market) FROM attrib").fetchone()[0] == pytest.approx(tot_before)   # nada de atribución se pierde
    recent = last - 48 * 3_600_000
    old_ts = [r[0] for r in led.con.execute("SELECT DISTINCT ts FROM equity WHERE ts < ? ORDER BY ts", (recent - 3_600_000,))]
    assert all((t + bar) % 3_600_000 == 0 for t in old_ts)                    # lo viejo: solo el cierre de cada hora
    n_recent = led.con.execute("SELECT COUNT(DISTINCT ts) FROM equity WHERE ts >= ?", (recent + 3_600_000,)).fetchone()[0]
    assert n_recent >= 48 * 4 - 8                                             # lo reciente queda completo
    assert led.compact_equity(last, bar) == 0                                 # idempotente
    # el equity que se conserva no cambia (solo se quitan filas)
    assert led.con.execute("SELECT equity FROM equity WHERE ts=? AND bot_id='a'", (old_ts[0],)).fetchone()[0] == pytest.approx(
        100 + ((old_ts[0] - start) // bar) * 1.0)
    led.close()


def test_compaction_is_noop_for_hourly_bars(tmp_path):
    led, start = _mk_ledger(tmp_path, INTERVAL_MS["1h"], 200)
    assert led.compact_equity(start + 199 * INTERVAL_MS["1h"], INTERVAL_MS["1h"]) == 0
    assert led.con.execute("SELECT COUNT(*) FROM equity").fetchone()[0] == 400
    led.close()


def test_family_rule_handles_repeated_kinds():
    assert family_of("d06_grid_btc") == "rango" and family_of("d10_mm_eth") == "rango"
    assert family_of("d02_carry_eth") == "neutral" and family_of("b10_xrp") == "neutral" and family_of("d14_xrp") == "neutral"
    assert family_of("b04_grid") == "rango" and family_of("zzz") == "otros"
