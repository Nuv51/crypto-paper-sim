"""Pruebas de los textos de notificación (scripts/digest.py).

Ejecuta:  python -m pytest -q
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import time
from argparse import Namespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from sim.cloud import run_step  # noqa: E402

spec = importlib.util.spec_from_file_location("digest", ROOT / "scripts" / "digest.py")
digest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(digest)


def capture(fn, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(Namespace(**kw))
    return buf.getvalue()


def two_runs(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    code, _ = run_step(config.BOTS, "1h", config.PORTFOLIO_CAPITAL, None, str(a), "synthetic", synthetic_advance=24)
    assert code == 0
    code, _ = run_step(config.BOTS, "1h", config.PORTFOLIO_CAPITAL, str(a / "ledger.json"), str(b), "synthetic", synthetic_advance=48)
    assert code == 0
    return a, b


def test_trade_notifications_only_when_something_new_happened(tmp_path):
    a, b = two_runs(tmp_path)
    same = capture(digest.cmd_trades, old=str(b / "dashboard.json"), new=str(b / "dashboard.json"))
    assert same == ""                                             # nada nuevo -> no hay aviso
    first = capture(digest.cmd_trades, old=None, new=str(a / "dashboard.json"))
    assert first == ""                                            # primera corrida: no inunda de avisos
    new = capture(digest.cmd_trades, old=str(a / "dashboard.json"), new=str(b / "dashboard.json"))
    assert "dinero ficticio" in new and "Portafolio:" in new
    assert "funding" not in new.lower().replace("funding negativo", "")     # el funding cobrado (3 al día) no se avisa


def test_noisy_bots_are_collapsed_into_one_line(tmp_path):
    a, b = two_runs(tmp_path)
    old, new = json.loads((a / "dashboard.json").read_text()), json.loads((b / "dashboard.json").read_text())
    new["trades"]["total"] = old["trades"]["total"] + 40
    row = ["1", "b06_mm", "binance", "BTCUSDT", "buy", "limit", 0.001, 70000.0, 70.0, 0.07, 0.0, "mm_bid"]
    new["trades"]["rows"] = new["trades"]["rows"][:-40] + [[1_700_000_000_000 + i * 3_600_000] + row[1:] for i in range(40)]
    (tmp_path / "o.json").write_text(json.dumps(old))
    (tmp_path / "n.json").write_text(json.dumps(new))
    out = capture(digest.cmd_trades, old=str(tmp_path / "o.json"), new=str(tmp_path / "n.json"))
    mm = [l for l in out.splitlines() if l.startswith("Market making")]
    assert len(mm) == 1 and "40 operaciones" in mm[0]


def test_digest_lists_every_bot_and_warns_when_the_simulator_stalls(tmp_path):
    a, b = two_runs(tmp_path)
    txt = capture(digest.cmd_digest, dashboard=str(b / "dashboard.json"), status=str(b / "status.json"))
    assert all(bot["name"] in txt for bot in config.BOTS)
    assert "Equity" in txt and "ficticio" in txt
    assert "no corre desde hace" not in txt                       # corrida recién hecha: sin advertencia
    # estado viejo: avisa
    st = json.loads((b / "status.json").read_text())
    st["ts"] = int(time.time() * 1000) - 7 * 3_600_000
    (tmp_path / "old_status.json").write_text(json.dumps(st))
    stale = capture(digest.cmd_digest, dashboard=str(b / "dashboard.json"), status=str(tmp_path / "old_status.json"))
    assert "no corre desde hace 7 h" in stale
    fresh = dict(st, ts=int(time.time() * 1000))
    (tmp_path / "fresh_status.json").write_text(json.dumps(fresh))
    ok = capture(digest.cmd_digest, dashboard=str(b / "dashboard.json"), status=str(tmp_path / "fresh_status.json"))
    assert "no corre desde hace" not in ok


def test_table_has_one_row_per_bot(tmp_path):
    _, b = two_runs(tmp_path)
    rows = capture(digest.cmd_table, dashboard=str(b / "dashboard.json")).strip().splitlines()
    assert len(rows) == 2 + len(config.BOTS) and rows[0].startswith("| Bot")
