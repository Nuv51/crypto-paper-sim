"""Pruebas del backtest V2 2019-2024: interruptor de volatilidad (sin mirar al futuro), tope de pérdida acumulada,
presupuesto de rotación, lectura del archivo de futuros de Binance y relleno de calentamiento."""
from __future__ import annotations

import io
import sys
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim.backtest import ArchiveHistoricFeed, parse_um_funding, parse_um_klines  # noqa: E402
from sim.engine import Engine  # noqa: E402
from sim.gates import btc_vol_gate  # noqa: E402
from sim.ledger import Ledger  # noqa: E402

H = 3_600_000


def _btc(n, calm_until, seed=1, daily_calm=0.005, daily_wild=0.04, calm_after=None):
    rng = np.random.default_rng(seed)
    sd = np.where(np.arange(n) < calm_until, daily_calm, daily_wild) / np.sqrt(24)
    if calm_after is not None:
        sd = np.where(np.arange(n) >= calm_after, daily_calm / np.sqrt(24), sd)
    path = 100 * np.exp(np.cumsum(rng.normal(0, 1, n) * sd))
    o = np.concatenate([[path[0]], path[:-1]])
    return pd.DataFrame({"open": o, "high": np.maximum(o, path) * 1.0002, "low": np.minimum(o, path) * 0.9998, "close": path,
                         "volume": np.full(n, 1000.0)}, index=pd.Index(np.arange(n, dtype="int64") * H, name="ts"))


def _run(bots, fr, capital=10_000.0):
    led = Ledger(Path(tempfile.mkdtemp(prefix="v2_")) / "t.db")
    eng = Engine(led, bots, capital, "1h", portfolio_risk=dict(max_drawdown=None, cooldown_bars=168))
    eng.replay(fr, progress=None)
    return eng, led


def _dca(**kw):
    risk = kw.pop("risk", dict(max_drawdown=0.45, action="flag_only"))
    return dict(id="t_dca", kind="dca", name="t", exchange="binance", symbols=["BTCUSDT"], capital_pct=1.0, risk_level="bajo",
                slippage_bps=2, params=dict(interval_hours=kw.pop("interval_hours", 24), contribution_pct=kw.pop("contribution_pct", 0.05)),
                risk=risk, **kw)


def test_gate_is_off_when_calm_on_when_wild_and_never_peeks_ahead():
    n = 24 * 60
    df = _btc(n, calm_until=24 * 30)
    ts = df.index.to_numpy()
    g = btc_vol_gate(df["close"].to_numpy(), ts)
    assert not g[24 * 16: 24 * 25].any() and g[-24:].all()
    alt = df["close"].to_numpy().copy()
    alt[24 * 40:] *= 0.3                                      # otro futuro a partir del día 40
    g2 = btc_vol_gate(alt, ts)
    assert (g[: 24 * 40] == g2[: 24 * 40]).all()              # hasta el día 40 el estado no cambia


def test_gate_evaluates_once_per_day_with_previous_closes():
    n = 24 * 40
    df = _btc(n, calm_until=n)
    g = btc_vol_gate(df["close"].to_numpy(), df.index.to_numpy())
    flips = np.flatnonzero(np.diff(g.astype(int)) != 0) + 1
    assert all((df.index[i] // H) % 24 == 0 for i in flips)   # solo cambia a las 00:00 UTC


def test_gated_bot_only_trades_while_gate_is_on_and_liquidates_when_it_turns_off():
    n = 24 * 90
    btc = _btc(n, calm_until=24 * 30, calm_after=24 * 60)     # calma, agitado, calma
    fr = {"BTCUSDT": btc}
    bot = _dca(gate=dict(type="btc_vol", symbol="BTCUSDT", lookback_days=14, threshold=0.40))
    eng, led = _run([bot], fr)
    tr = pd.read_sql_query("SELECT ts, side, reason FROM trades ORDER BY ts", led.con)
    ev = pd.read_sql_query("SELECT ts, message FROM events", led.con)
    on_ts = ev[ev.message.str.contains("ENCENDIDO|encendido")].ts.min()
    off_ts = ev[ev.message.str.contains("APAGADO")].ts.min()
    assert on_ts == on_ts and off_ts == off_ts and off_ts > on_ts
    buys = tr[(tr.side == "buy") & (tr.reason == "dca")]
    assert len(buys) > 0 and buys.ts.min() >= on_ts and buys.ts.max() <= off_ts + H       # compra solo con el interruptor encendido
    assert (tr[tr.reason == "risk_halt"].shape[0]) > 0                                       # al apagarse liquida
    assert eng.runtimes["t_dca"].wallet.pos("BTCUSDT").qty == 0


def test_ungated_bot_behaves_exactly_as_before():
    n = 24 * 40
    fr = {"BTCUSDT": _btc(n, calm_until=n)}
    a, la = _run([_dca()], fr)
    b, lb = _run([_dca(gate=None)], fr)
    qa = pd.read_sql_query("SELECT ts, qty FROM trades", la.con)
    qb = pd.read_sql_query("SELECT ts, qty FROM trades", lb.con)
    assert qa.equals(qb) and len(qa) > 0


def test_cumulative_loss_cap_retires_the_bot_even_if_it_keeps_making_new_peaks():
    n = 24 * 50
    path = np.r_[np.full(24 * 20, 100.0), np.linspace(100.0, 40.0, n - 24 * 20)]    # cae 60 %
    o = np.concatenate([[path[0]], path[:-1]])
    df = pd.DataFrame({"open": o, "high": np.maximum(o, path), "low": np.minimum(o, path), "close": path, "volume": 1000.0},
                      index=pd.Index(np.arange(n, dtype="int64") * H, name="ts"))
    bot = _dca(interval_hours=2, contribution_pct=0.2, risk=dict(max_drawdown=0.9, action="flag_only", max_loss_initial=0.05))
    eng, led = _run([bot], {"BTCUSDT": df})
    rt = eng.runtimes["t_dca"]
    assert rt.status == "retired" and "Pérdida acumulada" in rt.reason
    assert rt.wallet.pos("BTCUSDT").qty == 0                       # liquidó
    eq = pd.read_sql_query("SELECT equity FROM equity", led.con).equity
    assert eq.iloc[-1] > 10_000 * 0.9                              # no siguió perdiendo después del tope (≈ −5 % más costos)


def test_turnover_budget_pauses_until_next_month_and_resumes():
    n = 24 * 75
    df = _btc(n, calm_until=n, daily_calm=0.002)
    bot = _dca(interval_hours=2, contribution_pct=0.2, risk=dict(max_drawdown=0.9, action="flag_only", max_turnover_month=0.5))
    eng, led = _run([bot], {"BTCUSDT": df})
    ev = pd.read_sql_query("SELECT ts, message FROM events", led.con)
    assert ev.message.str.contains("Presupuesto de rotación").any()
    assert ev.message.str.contains("Reanuda sola").any()
    tr = pd.read_sql_query("SELECT ts, notional FROM trades", led.con)
    tr["month"] = pd.to_datetime(tr.ts, unit="ms", utc=True).dt.strftime("%Y-%m")
    per = tr.groupby("month").notional.sum()
    assert per.max() < 0.5 * 10_000 * 2.6                          # presupuesto + la liquidación de lo comprado (≈ 2×)


def test_parse_um_klines_and_funding_with_and_without_header():
    k_with = b"open_time,open,high,low,close,volume,close_time,quote_volume,count,tb,tq,ignore\n1577836800000,1,2,0.5,1.5,10,1,1,1,1,1,0\n1577840400000,1.5,2,1,1.2,11,1,1,1,1,1,0\n"
    k_without = k_with.split(b"\n", 1)[1]
    for raw in (k_with, k_without):
        df = parse_um_klines(raw)
        assert list(df.index) == [1577836800000, 1577840400000] and df["close"].iloc[1] == 1.2
    f_with = b"calc_time,funding_interval_hours,last_funding_rate\n1577865600001,8,0.0001\n1577894400002,8,-0.00005\n"
    for raw in (f_with, f_with.split(b"\n", 1)[1], b"1577865600001,0.0001\n"):
        d = parse_um_funding(raw)
        assert 1577865600000 in d


def _zip(name, raw):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(name, raw)
    return b.getvalue()


class _FakeResp:
    def __init__(self, status, content=b""):
        self.status_code, self.content = status, content

    def raise_for_status(self):
        pass


def test_archive_feed_fills_leading_warmup_from_spot_but_refuses_big_gaps():
    day = 24 * H
    start = 1577836800000                                       # 2020-01-01
    rows = "".join(f"{start + i * H},100,101,99,100.5,1,1,1,1,1,1,0\n" for i in range(24 * 31))
    fund = "".join(f"{start + i * 8 * H + 1},8,0.0001\n" for i in range(3 * 31))
    files = {"BTCUSDT-1h-2020-01.zip": _zip("k.csv", rows.encode()), "BTCUSDT-fundingRate-2020-01.zip": _zip("f.csv", fund.encode())}

    class Feed(ArchiveHistoricFeed):
        def __init__(self):
            super().__init__(cache_dir=tempfile.mkdtemp(prefix="ar_"), pause=0)
            self.session = type("S", (), {"get": lambda s, url, timeout=None: _FakeResp(200, files[url.rsplit("/", 1)[1]]) if url.rsplit("/", 1)[1] in files else _FakeResp(404)})()

        def closed_range(self, symbol, interval, s, e):         # spot sintético para el relleno
            idx = np.arange(s, e, H, dtype="int64")
            return pd.DataFrame({"open": 99.0, "high": 99.5, "low": 98.5, "close": 99.0, "volume": 5.0}, index=pd.Index(idx, name="ts"))

    f = Feed()
    df = f._perp_range("BTCUSDT~PERP", "1h", start - 60 * H, start + 31 * day)         # 60 h antes del archivo
    assert df.index[0] == start - 60 * H and len(df) == 60 + 24 * 31
    assert df["funding"].iloc[:60].isna().all() and df["funding"].notna().sum() == 3 * 31
    assert (df["close"].iloc[:60] == 99.0).all()               # relleno con spot
    try:
        f._perp_range("BTCUSDT~PERP", "1h", start - 90 * day, start + 31 * day)        # faltan 90 días
    except RuntimeError as e:
        assert "faltan" in str(e)
    else:
        raise AssertionError("debió negarse a rellenar un hueco grande")


def test_gate_is_time_based_and_robust_to_data_gaps():
    """Con huecos de datos (mantenimiento del exchange) el interruptor mira las mismas HORAS, no las mismas posiciones."""
    import numpy as np
    from sim.gates import btc_vol_gate
    H = 3_600_000
    n = 24 * 40
    ts = np.arange(n, dtype=np.int64) * H
    rng = np.random.default_rng(1)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.012, n)))
    full = btc_vol_gate(close, ts, 14, 0.40)
    keep = np.ones(n, dtype=bool)
    keep[24 * 20 + 3: 24 * 20 + 9] = False                    # seis horas sin datos, lejos de las 23:00 que se leen
    gap = btc_vol_gate(close[keep], ts[keep], 14, 0.40)
    assert np.array_equal(gap, full[keep])
    keep2 = np.ones(n, dtype=bool)
    keep2[24 * 25: 24 * 25 + 2] = False                       # falta la vela de las 00:00: evalúa en la primera del día
    g2 = btc_vol_gate(close[keep2], ts[keep2], 14, 0.40)
    assert g2.shape == (keep2.sum(),) and g2[ts[keep2] < 24 * 25 * H].tolist() == full[ts < 24 * 25 * H].tolist()


def test_replay_starts_on_the_date_even_when_warmup_has_gaps():
    import tempfile
    import numpy as np
    from pathlib import Path
    from sim.backtest import run_backtest
    from tests.test_backtest import _cfg
    from tests.test_index import frames
    H = 3_600_000
    fr = frames(240)
    for s in fr:                                              # quita 5 horas en pleno calentamiento (todas las monedas, como un mantenimiento)
        fr[s] = fr[s][~((fr[s].index >= 10 * H) & (fr[s].index < 15 * H))]
    out = tempfile.mkdtemp(prefix="bt_")
    s = run_backtest(_cfg(), dict(id="bt-t", name="t"), out, start="1970-01-04", end="1970-01-11", feed=object(), frames=fr, log=lambda *_: None)
    assert s["first_ts"] == 72 * H and s["last_ts"] == 239 * H
