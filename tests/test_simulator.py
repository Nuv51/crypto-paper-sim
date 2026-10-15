"""Pruebas del simulador: contabilidad, reglas de ejecución y ausencia de look-ahead.

Ejecuta:  python -m pytest -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from sim import indicators as ind  # noqa: E402
from sim.bots import Ctx  # noqa: E402
from sim.broker import PaperWallet  # noqa: E402
from sim.data import SyntheticFeed  # noqa: E402
from sim.engine import Engine  # noqa: E402
from sim.exchanges import EXCHANGES  # noqa: E402
from sim.ledger import Ledger, read_only_connection  # noqa: E402
from sim.metrics import load_all  # noqa: E402

H = 3_600_000
BINANCE = EXCHANGES["binance"]


def wallet(cash=1000.0, slip=0.0):
    return PaperWallet("t", BINANCE, cash, slippage_bps=slip)


# ----------------------------------------------------------------------------- broker
def test_buy_then_sell_accounting_includes_fees():
    w = wallet()
    w.submit(0, "XUSDT", "buy", "market", 1.0)
    (f1,) = w.process_bar(H, "XUSDT", 100, 101, 99, 100)
    assert f1.price == 100 and f1.fee == pytest.approx(0.1)
    assert w.cash == pytest.approx(1000 - 100.1)
    assert w.pos("XUSDT").avg_cost == pytest.approx(100.1)

    w.submit(H, "XUSDT", "sell", "market", 1.0)
    (f2,) = w.process_bar(2 * H, "XUSDT", 110, 111, 109, 110)
    assert f2.realized_pnl == pytest.approx(110 - 100.1 - 0.11)
    assert w.cash == pytest.approx(1000 - 100.1 + 110 - 0.11)
    marks = {"XUSDT": 110.0}
    assert w.equity(marks) == pytest.approx(w.initial_cash + w.realized_pnl + w.unrealized(marks))
    assert w.pos("XUSDT").qty == 0


def test_slippage_is_adverse():
    w = wallet(slip=10)  # 10 bps
    w.submit(0, "XUSDT", "buy", "market", 1.0)
    (f,) = w.process_bar(H, "XUSDT", 100, 100, 100, 100)
    assert f.price == pytest.approx(100.1)
    w.submit(H, "XUSDT", "sell", "market", 1.0)
    (g,) = w.process_bar(2 * H, "XUSDT", 100, 100, 100, 100)
    assert g.price == pytest.approx(99.9)


def test_order_never_fills_in_the_bar_it_was_sent():
    w = wallet()
    w.submit(5 * H, "XUSDT", "buy", "market", 1.0)
    assert w.process_bar(5 * H, "XUSDT", 100, 100, 100, 100) == []
    w.submit(5 * H, "XUSDT", "buy", "limit", 1.0, price=100.0)
    assert w.process_bar(5 * H, "XUSDT", 100, 100, 50, 100) == []


def test_limit_fills_only_when_price_crosses_strictly():
    w = wallet()
    w.submit(0, "XUSDT", "buy", "limit", 1.0, price=100.0)
    assert w.process_bar(H, "XUSDT", 101, 102, 100.0, 101) == []          # solo toca el nivel
    (f,) = w.process_bar(2 * H, "XUSDT", 101, 102, 99.99, 101)           # lo cruza
    assert f.price == 100.0 and f.kind == "limit"
    assert f.fee == pytest.approx(100.0 * BINANCE.maker)


def test_cannot_spend_the_same_cash_twice():
    w = wallet(1000)
    assert w.submit(0, "XUSDT", "buy", "limit", 5.0, price=100.0) is not None   # reserva ~500
    assert w.submit(0, "XUSDT", "buy", "limit", 6.0, price=100.0) is None        # no alcanza
    assert any("efectivo libre" in m for _, m in w.drain_events())


def test_cannot_oversell_and_market_sell_is_clipped():
    w = wallet()
    w.submit(0, "XUSDT", "buy", "market", 2.0)
    w.process_bar(H, "XUSDT", 100, 100, 100, 100)
    assert w.submit(H, "XUSDT", "sell", "limit", 3.0, price=120.0) is None
    w.submit(H, "XUSDT", "sell", "market", 5.0)
    (f,) = w.process_bar(2 * H, "XUSDT", 100, 100, 100, 100)
    assert f.qty == pytest.approx(2.0)


def test_market_buy_is_clipped_to_available_cash_never_negative():
    w = wallet(100)
    w.submit(0, "XUSDT", "buy", "market", 10.0)   # pediría 1000 USDT
    (f,) = w.process_bar(H, "XUSDT", 100, 100, 100, 100)
    assert w.cash >= -1e-9
    assert f.qty < 1.0


def test_wallet_state_roundtrip():
    w = wallet()
    w.submit(0, "XUSDT", "buy", "market", 1.0)
    w.process_bar(H, "XUSDT", 100, 100, 100, 100)
    w.submit(H, "XUSDT", "sell", "limit", 1.0, price=120.0, tag="S1")
    w2 = wallet()
    w2.load_dict(w.to_dict())
    assert w2.to_dict() == w.to_dict()


# ----------------------------------------------------------------------------- indicadores
@pytest.fixture(scope="module")
def df():
    return SyntheticFeed(seed=3).history("ETHUSDT", "1h", 40)


def test_indicators_are_causal(df):
    k = 500
    cuts = {
        "rsi": lambda d: ind.rsi(d["close"], 14),
        "ema": lambda d: ind.ema(d["close"], 24),
        "atr": lambda d: ind.atr(d, 14),
        "bb_lo": lambda d: ind.bollinger(d["close"], 20, 2.0)[2],
        "don_hi": lambda d: ind.donchian_high(d, 48),
        "don_lo": lambda d: ind.donchian_low(d, 24),
        "roc": lambda d: ind.roc(d["close"], 72),
    }
    for name, fn in cuts.items():
        full = fn(df).iloc[k - 1]
        part = fn(df.iloc[:k]).iloc[-1]
        assert full == pytest.approx(part, rel=1e-12, nan_ok=True), name


def test_every_bot_indicator_is_causal():
    """Para cada bot y moneda: el indicador en la barra k calculado con datos hasta k debe ser idéntico
    al calculado con TODO el historial. Detecta cualquier mirada al futuro (shift negativo, etc.)."""
    feed = SyntheticFeed(seed=5)
    eng = Engine(Ledger(":memory:"), config.BOTS, 10_000, "1h")
    frames = {s: feed.history(s, "1h", 60) for s in eng.symbols}
    checked = 0
    for rt in eng.runtimes.values():
        for sym in rt.bot.symbols:
            full = rt.bot.prepare(sym, frames[sym])
            for k in (400, 777, 1100, 1300):
                part = rt.bot.prepare(sym, frames[sym].iloc[:k])
                for col in full.columns:
                    a, b = full[col].iloc[k - 1], part[col].iloc[-1]
                    assert a == pytest.approx(b, rel=1e-12, nan_ok=True), (rt.bot.id, sym, col, k)
                    checked += 1
    assert checked > 100


def test_donchian_excludes_current_bar(df):
    hi = ind.donchian_high(df, 48)
    i = 200
    assert hi.iloc[i] == df["high"].iloc[i - 48:i].max()


# ----------------------------------------------------------------------------- motor completo
def run_replay(tmp_path, days=70, seed=7, name="a.db", cut_bars=None):
    feed = SyntheticFeed(seed=seed)
    ledger = Ledger(tmp_path / name)
    eng = Engine(ledger, config.BOTS, config.PORTFOLIO_CAPITAL, config.INTERVAL)
    frames = {s: feed.history(s, config.INTERVAL, days + 15) for s in eng.symbols}
    if cut_bars:
        frames = {s: f.iloc[:cut_bars] for s, f in frames.items()}
    eng.replay(frames, progress=None)
    ledger.close()
    return eng, load_all(read_only_connection(tmp_path / name))


def test_replay_accounting_invariants(tmp_path):
    eng, data = run_replay(tmp_path)
    eq, tr = data["equity"], data["trades"]
    assert len(tr) > 0
    assert (eq.cash >= -1e-6).all(), "efectivo negativo"
    assert (tr.qty > 0).all() and (tr.price > 0).all() and (tr.fee >= 0).all()
    for bid, rt in eng.runtimes.items():
        w, e, t = rt.wallet, eq[eq.bot_id == bid], tr[tr.bot_id == bid]
        last = e.iloc[-1]
        # identidad contable en cada fila
        resid = e.equity - (w.initial_cash + e.realized_pnl + e.unrealized_pnl)
        assert resid.abs().max() < 1e-6, bid
        # el efectivo final se reconstruye desde las operaciones
        flow = np.where(t.side == "sell", t.notional - t.fee, -(t.notional + t.fee)).sum()
        assert w.cash == pytest.approx(w.initial_cash + flow, abs=1e-6), bid
        assert t.realized_pnl.sum() == pytest.approx(w.realized_pnl, abs=1e-6), bid
        assert t.fee.sum() == pytest.approx(w.fees_paid, abs=1e-6), bid
        assert last.equity == pytest.approx(w.cash + sum(
            p.qty * data["bars"][(data["bars"].symbol == s) & (data["bars"].ts == last.ts)].close.iloc[0]
            for s, p in w.positions.items() if p.qty > 0), abs=1e-6), bid
        # spot long-only
        assert all(p.qty >= -1e-12 for p in w.positions.values()), bid


def test_replay_is_deterministic(tmp_path):
    _, a = run_replay(tmp_path, name="a.db")
    _, b = run_replay(tmp_path, name="b.db")
    pd.testing.assert_frame_equal(a["equity"], b["equity"])
    pd.testing.assert_frame_equal(a["trades"].drop(columns="id"), b["trades"].drop(columns="id"))


def test_no_lookahead_in_strategies(tmp_path):
    """Si una estrategia usara datos futuros, truncar el historial cambiaría el pasado simulado."""
    _, long = run_replay(tmp_path, days=70, name="long.db")
    n_short = int(long["bars"].groupby("symbol").size().iloc[0]) - 400      # recorta ~17 días del final
    # mismo historial base pero cortado: se alinea por timestamps, no por posición
    feed = SyntheticFeed(seed=7)
    ledger = Ledger(tmp_path / "short.db")
    eng = Engine(ledger, config.BOTS, config.PORTFOLIO_CAPITAL, config.INTERVAL)
    frames = {s: feed.history(s, config.INTERVAL, 70 + 15) for s in eng.symbols}
    cut_ts = int(sorted(frames["BTCUSDT"].index)[-400])
    frames = {s: f[f.index <= cut_ts] for s, f in frames.items()}
    eng.replay(frames, progress=None)
    ledger.close()
    short = load_all(read_only_connection(tmp_path / "short.db"))

    a = long["equity"][long["equity"].ts <= cut_ts].reset_index(drop=True)
    b = short["equity"][short["equity"].ts <= cut_ts].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)
    ta = long["trades"][long["trades"].ts <= cut_ts].drop(columns="id").reset_index(drop=True)
    tb = short["trades"][short["trades"].ts <= cut_ts].drop(columns="id").reset_index(drop=True)
    assert len(a) > 500 and len(ta) > 0, "la comparación sería vacía"
    pd.testing.assert_frame_equal(ta, tb)


def _engine_with(tmp_path, bot_id):
    ledger = Ledger(tmp_path / f"{bot_id}.db")
    eng = Engine(ledger, config.BOTS, 10_000, "1h", only=[bot_id])
    rt = eng.runtimes[bot_id]
    arrays = {s: {"close": np.array([100.0, 100.0, 100.0])} for s in rt.bot.symbols}
    return eng, rt, Ctx(2 * H, 2, rt.wallet, arrays, H)


def test_risk_guard_liquidate_and_halt(tmp_path):
    eng, rt, ctx = _engine_with(tmp_path, "b07_trend")
    w = rt.wallet
    w.submit(0, "SOLUSDT", "buy", "market", 1.0)
    w.process_bar(H, "SOLUSDT", 100, 100, 100, 100)
    eng._risk_check(rt, ctx, rt.peak * (1 - 0.20))            # drawdown 20% > límite 15%
    assert rt.status == "halted"
    assert any(o.side == "sell" and o.kind == "market" for o in w.orders)   # liquidación enviada
    assert eng._events[-1][2] == "alert"


def test_risk_guard_flag_only_keeps_trading(tmp_path):
    eng, rt, ctx = _engine_with(tmp_path, "b03_dca")
    eng._risk_check(rt, ctx, rt.peak * (1 - 0.50))            # drawdown 50% > 45%
    assert rt.status == "active" and rt.flagged and "REVISIÓN MANUAL" in rt.reason
    assert rt.wallet.orders == []                              # no liquida: el DCA no tiene stop-loss


def test_risk_guard_pause_then_resume(tmp_path):
    eng, rt, ctx = _engine_with(tmp_path, "b08_breakout")
    eng._risk_check(rt, ctx, rt.peak * (1 - 0.25))            # > 17%
    assert rt.status == "paused" and rt.pause_until > ctx.ts
    later = Ctx(rt.pause_until, 2, rt.wallet, ctx.arrays, H)
    eng._risk_check(rt, later, rt.wallet.initial_cash * 0.75)
    assert rt.status == "active" and rt.peak == pytest.approx(rt.wallet.initial_cash * 0.75)


def test_ctx_blocks_future_access(tmp_path):
    _, rt, ctx = _engine_with(tmp_path, "b07_trend")
    with pytest.raises(ValueError):
        ctx.v("SOLUSDT", "close", back=-1)


# ----------------------------------------------------------------------------- feed de Binance (sin red)
class _FakeBinance:
    """Sustituye la capa HTTP: sirve velas 1h con el mismo formato que /api/v3/klines."""
    def __init__(self, now_ms):
        self.now_ms, self.calls = now_ms, []

    def get(self, path, params, retries=4):
        self.calls.append(dict(params))
        start = params.get("startTime", self.now_ms - 3000 * H)
        t = (start // H) * H if start % H == 0 else (start // H + 1) * H
        rows = []
        while t <= self.now_ms and len(rows) < params["limit"]:
            rows.append([t, "100", "101", "99", "100.5", "10", t + H - 1, "0", 0, "0", "0", "0"])
            t += H
        return rows


def test_binance_feed_paginates_caches_and_drops_forming_candle(tmp_path):
    import time as _time
    from sim.data import BinanceFeed
    now_s = 1_800_000_000 + 1800            # a mitad de una hora: la última vela está en formación
    now_ms = now_s * 1000
    real_time = _time.time
    _time.time = lambda: now_s
    try:
        feed = BinanceFeed(cache_dir=tmp_path, pause=0)
        fake = _FakeBinance(now_ms)
        feed._get = fake.get
        df = feed.history("XUSDT", "1h", days=100)
        assert len(fake.calls) >= 3, "debe paginar (1000 velas por llamada)"
        assert df.index.is_monotonic_increasing and not df.index.has_duplicates
        assert int(df.index[-1]) + H - 1 < now_ms, "incluyó la vela en formación"
        n1 = len(df)

        fake.calls.clear()
        feed.history("XUSDT", "1h", days=100)                      # sin velas nuevas: solo pide lo nuevo
        assert len(fake.calls) == 1 and fake.calls[0]["startTime"] > int(df.index[-1]) - 1

        _time.time = lambda: now_s + 3 * 3600                       # pasan 3 horas
        fake.now_ms = (now_s + 3 * 3600) * 1000
        fake.calls.clear()
        df2 = feed.history("XUSDT", "1h", days=100)
        assert fake.calls[0]["startTime"] == int(df.index[-1]) + H, "solo debe pedir desde la última vela cacheada"
        assert int(df2.index[-1]) == int(df.index[-1]) + 3 * H, "debe avanzar exactamente 3 velas"
        assert not df2.index.has_duplicates
    finally:
        _time.time = real_time


# ----------------------------------------------------------------------------- modo live (sin red)
def _window(full, k, n=700):
    return {s: f.iloc[max(0, k - n):k] for s, f in full.items()}


def test_live_resume_matches_uninterrupted(tmp_path):
    """Detener y reanudar con un Engine nuevo (estado en SQLite) debe dar EXACTAMENTE lo mismo
    que una sesión ininterrumpida, procesando una barra nueva por vez."""
    feed = SyntheticFeed(seed=11)
    syms = sorted({s for b in config.BOTS for s in b["symbols"]})
    full = {s: feed.history(s, "1h", 60) for s in syms}
    N = 1000

    def make(name):
        led = Ledger(tmp_path / name)
        return led, Engine(led, config.BOTS, 10_000, "1h")

    la, ea = make("a.db")
    for k in range(N, N + 120):
        assert ea.process_new(_window(full, k)) == 1
    la.close()

    lb, eb = make("b.db")
    for k in range(N, N + 60):
        eb.process_new(_window(full, k))
    lb.close()
    lb2, eb2 = make("b.db")                      # "reinicio del programa"
    assert eb2.has_saved_state()
    eb2.load_state()
    for k in range(N + 60, N + 120):
        eb2.process_new(_window(full, k))
    lb2.close()

    A, B = load_all(read_only_connection(tmp_path / "a.db")), load_all(read_only_connection(tmp_path / "b.db"))
    assert len(A["equity"]) == 120 * len(config.BOTS)
    pd.testing.assert_frame_equal(A["equity"], B["equity"])
    pd.testing.assert_frame_equal(A["trades"].drop(columns="id"), B["trades"].drop(columns="id"))


def test_live_skips_already_processed_bars_and_survives_feed_errors(tmp_path):
    feed = SyntheticFeed(seed=11)
    syms = sorted({s for b in config.BOTS for s in b["symbols"]})
    full = {s: feed.history(s, "1h", 60) for s in syms}

    class Flaky:
        def __init__(self): self.failed = False
        def latest_closed(self, sym, interval, n):
            if not self.failed:                        # el primer ciclo falla (red caída)
                self.failed = True
                raise ConnectionError("sin red")
            return _window(full, 1000)[sym]

    led = Ledger(tmp_path / "l.db")
    eng = Engine(led, config.BOTS, 10_000, "1h")
    logs = []
    eng.live(Flaky(), poll_seconds=0, max_loops=3, log=logs.append)
    assert any("error" in m for m in logs)
    n = led.con.execute("SELECT COUNT(DISTINCT ts) FROM equity").fetchone()[0]
    assert n == 1, "la misma vela no debe procesarse dos veces"
    led.close()
