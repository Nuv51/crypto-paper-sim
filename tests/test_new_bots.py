"""Pruebas de los bots #1 carry, #2 stablecoins, #6 market making, #9 ML y #10 arbitraje XRP, y de sus fuentes de datos.

Ejecuta:  python -m pytest -q
"""
from __future__ import annotations

import copy
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from sim import data as simdata  # noqa: E402
from sim.bots import Ctx, MLBot, build_bot, fit_logreg  # noqa: E402
from sim.broker import PaperWallet  # noqa: E402
from sim.cloud import run_step  # noqa: E402
from sim.data import MarketFeed, parse_kucoin_funding, parse_kucoin_futures_klines  # noqa: E402
from sim.engine import Engine  # noqa: E402
from sim.exchanges import get_exchange  # noqa: E402
from sim.ledger import Ledger, read_only_connection  # noqa: E402
from sim.metrics import load_all  # noqa: E402

H = 3_600_000
CAP = config.PORTFOLIO_CAPITAL


def cfg(bot_id, **param_over):
    c = copy.deepcopy(next(b for b in config.BOTS if b["id"] == bot_id))
    c["params"].update(param_over)
    return c


def df_from(close, wick=0.0, **extra):
    close = np.asarray(close, dtype=float)
    n = len(close)
    open_ = np.concatenate([[close[0]], close[:-1]])
    out = pd.DataFrame({"open": open_, "high": np.maximum(open_, close) * (1 + wick),
                        "low": np.minimum(open_, close) * (1 - wick), "close": close, "volume": np.full(n, 100.0)},
                       index=pd.Index(np.arange(n, dtype="int64") * H, name="ts"))
    for k, v in extra.items():
        out[k] = v
    return out


def run(tmp_path, bot_cfg, frames, name="x.db"):
    ledger = Ledger(tmp_path / name)
    eng = Engine(ledger, [bot_cfg], CAP, "1h")
    eng.replay(frames, progress=None)
    ledger.close()
    return eng, load_all(read_only_connection(tmp_path / name))


# =============================================================================== broker
def test_book_keeps_the_accounting_identity():
    w = PaperWallet("t", get_exchange("kucoin"), 1000.0)
    w.book(0, "X~PERP", "buy", "perp", 1.0, 100.0, fee=0.5, realized=-0.5, reason="open")
    w.extra_value = 12.0
    assert w.equity({}) == pytest.approx(w.initial_cash + w.realized_pnl + w.unrealized({}))
    assert w.fees_paid == 0.5 and len(w.drain_extra_fills()) == 1 and w.drain_extra_fills() == []
    w2 = PaperWallet("t", get_exchange("kucoin"), 1000.0)
    w2.load_dict(w.to_dict())
    assert w2.extra_value == 12.0 and w2.to_dict() == w.to_dict()


# =============================================================================== #1 carry
def carry_frames(spot_path, funding_rate, basis=0.0005, funding_from=0, funding_rate2=None, switch=None):
    n = len(spot_path)
    spot = df_from(spot_path)
    perp = df_from(np.asarray(spot_path) * (1 + basis))
    fund = np.full(n, np.nan)
    for k in range(funding_from, n):
        if k % 8 == 0:
            fund[k] = funding_rate2 if (switch is not None and k >= switch) else funding_rate
    perp["funding"] = fund
    return {"BTCUSDT": spot, "BTCUSDT~PERP": perp}


def test_carry_is_delta_neutral_and_earns_funding(tmp_path):
    n = 300
    up = np.concatenate([np.full(120, 100.0), np.linspace(100, 125, 80), np.full(100, 125.0)])
    down = np.concatenate([np.full(120, 100.0), np.linspace(100, 80, 80), np.full(100, 80.0)])
    pnl = {}
    for name, path in (("up", up), ("down", down)):
        eng, d = run(tmp_path, cfg("b01_carry"), carry_frames(path, 0.0003), name=f"{name}.db")
        t, e = d["trades"], d["equity"]
        w, st = eng.runtimes["b01_carry"].wallet, eng.runtimes["b01_carry"].bot.st
        assert (t.kind == "perp").sum() == 1 and (t.kind == "funding").sum() > 5
        assert st["perp_qty"] == pytest.approx(w.pos("BTCUSDT").qty)             # cobertura exacta
        assert (e.cash >= -1e-6).all()
        resid = e.equity - (w.initial_cash + e.realized_pnl + e.unrealized_pnl)
        assert resid.abs().max() < 1e-6
        fund = t[t.kind == "funding"].realized_pnl.sum()
        assert fund > 0 and fund == pytest.approx(st["funding_total"])
        total = float(e.equity.iloc[-1] - w.initial_cash)
        assert total == pytest.approx(fund - w.fees_paid, abs=1.0), name           # P&L = funding - costos
        pnl[name] = total - fund                                                   # lo que NO es funding: costos + basis
    # una posición solo larga ganaría/perdería ~190 USDT. En el carry, sin contar el funding (que depende del
    # monto nocional y por eso difiere entre trayectorias), el resultado es el mismo suba o baje el precio.
    assert abs(pnl["up"] - pnl["down"]) < 0.5 and abs(pnl["up"]) < 5


def test_carry_waits_when_funding_is_below_its_cost_hurdle(tmp_path):
    eng, d = run(tmp_path, cfg("b01_carry"), carry_frames(np.full(200, 100.0), 0.00005))   # ~5% anual < costos
    assert len(d["trades"]) == 0
    assert "Esperando" in eng.runtimes["b01_carry"].bot.status_detail(eng.runtimes["b01_carry"].wallet)


def test_carry_exits_after_three_negative_periods(tmp_path):
    path = np.full(260, 100.0)
    eng, d = run(tmp_path, cfg("b01_carry"), carry_frames(path, 0.0003, funding_rate2=-0.0002, switch=120))
    t = d["trades"]
    closes = t[(t.reason == "funding_negative")]
    assert set(closes.kind) == {"market", "perp"} and len(closes) == 2
    st = eng.runtimes["b01_carry"].bot.st
    assert st["perp_qty"] == 0 and eng.runtimes["b01_carry"].wallet.extra_value == 0
    assert eng.runtimes["b01_carry"].wallet.pos("BTCUSDT").qty == 0


def test_carry_closes_both_legs_on_margin_stress(tmp_path):
    path = np.concatenate([np.full(100, 100.0), np.linspace(100, 160, 60), np.full(80, 160.0)])
    eng, d = run(tmp_path, cfg("b01_carry"), carry_frames(path, 0.0003))
    assert (d["trades"].reason == "margin_stress").sum() == 2                  # cierra las dos patas
    assert d["equity"].equity.min() > eng.runtimes["b01_carry"].wallet.initial_cash * 0.97   # sin liquidación ni pérdida direccional


def test_carry_funding_is_not_paid_on_the_bar_it_opens(tmp_path):
    path = np.full(150, 100.0)
    # el funding aparece justo en cada barra k%8==0; la apertura ocurre en una barra de liquidación si coincide
    eng, d = run(tmp_path, cfg("b01_carry"), carry_frames(path, 0.0003))
    t = d["trades"]
    opened = int(t[t.kind == "perp"].ts.iloc[0])
    assert not ((t.kind == "funding") & (t.ts == opened)).any()


# =============================================================================== #2 stablecoins
def stable_frames(usdc, fdusd=None):
    return {"USDCUSDT": df_from(usdc, wick=0.0001), "FDUSDUSDT": df_from(np.full(len(usdc), 1.0) if fdusd is None else fdusd, wick=0.0001)}


def test_stable_idle_at_the_peg_and_profits_from_a_real_deviation(tmp_path):
    n = 200
    flat = np.full(n, 1.0)
    _, d = run(tmp_path, cfg("b02_stable"), stable_frames(flat), name="flat.db")
    assert len(d["trades"]) == 0
    dip = flat.copy()
    dip[100:104] = 0.9960              # desvío de 0.40% (> umbral de 0.30%)
    eng, d = run(tmp_path, cfg("b02_stable"), stable_frames(dip), name="dip.db")
    t = d["trades"]
    assert list(t.side) == ["buy", "sell"] and t.reason.iloc[1] == "peg_restored"
    assert t.realized_pnl.iloc[1] > 0 and t.symbol.iloc[0] == "USDCUSDT"


def test_stable_small_deviation_is_not_worth_the_fees(tmp_path):
    n = 200
    p = np.full(n, 1.0)
    p[100:104] = 0.9985                # 0.15%: con comisiones de 0.1% por lado perdería dinero -> no opera
    _, d = run(tmp_path, cfg("b02_stable"), stable_frames(p))
    assert len(d["trades"]) == 0


def test_stable_does_not_catch_a_falling_knife(tmp_path):
    n = 260
    p = np.full(n, 1.0)
    p[100:] = 0.97                     # de-peg de 3% y sostenido: no se compra (guard 1.5%)
    _, d = run(tmp_path, cfg("b02_stable"), stable_frames(p))
    assert len(d["trades"]) == 0
    q = np.full(n, 1.0)
    q[100:103] = 0.9960                # entra en un desvío "normal"...
    q[103:] = 0.975                    # ...y luego el peg se rompe de verdad
    eng, d = run(tmp_path, cfg("b02_stable"), stable_frames(q), name="depeg.db")
    sells = d["trades"][d["trades"].side == "sell"]
    assert len(sells) == 1 and sells.reason.iloc[0] in ("depeg_exit", "stop")


# =============================================================================== #6 market making
def mm_ctx(price=100.0, ratio=0.5, atr=0.4):
    c = cfg("b06_mm")
    bot = build_bot(dict(c, capital=800.0), H)
    w = PaperWallet(bot.id, get_exchange("binance"), 800.0, 1)
    qty = ratio * 800.0 / price
    w.positions["BTCUSDT"] = type(w.pos("BTCUSDT"))(qty, price)
    w.cash = 800.0 - qty * price
    arrays = {"BTCUSDT": {"close": np.array([price] * 3), "atr": np.array([atr] * 3)}}
    bot.st["init"] = True
    return bot, w, Ctx(2 * H, 2, w, arrays, H)


def test_mm_quotes_symmetrically_when_inventory_is_balanced():
    bot, w, ctx = mm_ctx(ratio=0.5)
    bot.on_bar(ctx)
    bid = next(o for o in w.orders if o.side == "buy")
    ask = next(o for o in w.orders if o.side == "sell")
    assert bid.price == pytest.approx(100 * (1 - 0.0015)) and ask.price == pytest.approx(100 * (1 + 0.0015))


def test_mm_stops_adding_to_a_heavy_inventory_and_skews_quotes():
    bot, w, ctx = mm_ctx(ratio=0.75)                    # +25 pts sobre el objetivo: supera quote_stop_dev (20)
    bot.on_bar(ctx)
    assert [o.side for o in w.orders] == ["sell"]       # no sigue comprando
    assert w.orders[0].price < 100 * (1 + 0.0015)       # y vende más barato para descargar inventario
    bot, w, ctx = mm_ctx(ratio=0.25)
    bot.on_bar(ctx)
    assert [o.side for o in w.orders] == ["buy"]


def test_mm_rebalances_at_market_beyond_the_limit_and_pulls_quotes_in_high_vol():
    bot, w, ctx = mm_ctx(ratio=0.85)
    bot.on_bar(ctx)
    assert [(o.side, o.kind) for o in w.orders] == [("sell", "market")]
    bot, w, ctx = mm_ctx(ratio=0.5, atr=2.0)            # ATR 2% > vol_guard 1.2%
    bot.on_bar(ctx)
    assert w.orders == [] and "volatilidad" in bot.st["note"]


# =============================================================================== #9 ML
def test_logreg_learns_a_real_signal_and_is_deterministic():
    rng = np.random.default_rng(0)
    X = rng.standard_normal((2000, 4))
    y = (X @ np.array([1.5, -1.0, 0.0, 0.5]) + 0.3 * rng.standard_normal(2000) > 0).astype(float)
    w1, w2 = fit_logreg(X, y), fit_logreg(X, y)
    assert np.array_equal(w1, w2)
    pred = (1 / (1 + np.exp(-(X @ w1[:-1] + w1[-1]))) > 0.5)
    assert (pred == (y > 0)).mean() > 0.9
    assert abs(w1[2]) < 0.2                              # ignora la variable sin información


def test_ml_trains_only_on_known_labels_and_state_is_json(tmp_path):
    from sim.data import SyntheticFeed
    feed = SyntheticFeed(seed=11)
    frames = {s: feed.history(s, "1h", 60) for s in ("BTCUSDT", "ETHUSDT", "XRPUSDT")}
    eng, d = run(tmp_path, cfg("b09_ml"), frames)
    bot = eng.runtimes["b09_ml"].bot
    st = bot.get_state()
    assert json.loads(json.dumps(st)) == st and st["n_models"] >= 1 and st["oos_n"] > 100
    bot2 = build_bot(dict(cfg("b09_ml"), capital=500.0), H)
    bot2.set_state(st)
    f = [0.001, 0.002, 0.003, 0.0, 0.01, 0.005, 1.0, 0.1, 0.01, 0.5, 0.01]
    assert bot2._predict(f) == pytest.approx(bot._predict(f))
    assert 0.0 < bot._predict(f) < 1.0


def test_ml_never_trades_below_its_confidence_threshold(tmp_path):
    from sim.data import SyntheticFeed
    feed = SyntheticFeed(seed=11)
    frames = {s: feed.history(s, "1h", 60) for s in ("BTCUSDT", "ETHUSDT", "XRPUSDT")}
    _, d = run(tmp_path, cfg("b09_ml", thr=0.99), frames)
    assert len(d["trades"]) == 0


# =============================================================================== #10 arbitraje XRP
RAIL = "XRP~RAIL"


def rail_ctx(quotes, ts=2 * H, fees=None):
    c = cfg("b10_xrp")
    bot = build_bot(dict(c, capital=1000.0), H)
    w = PaperWallet(bot.id, get_exchange("cross"), 1000.0, 0)
    cols = {}
    for v in ("bitso", "binance", "kucoin"):
        bid, ask, bq, aq = quotes.get(v, (np.nan,) * 4)
        for name, val in zip(("bid", "ask", "bq", "aq"), (bid, ask, bq, aq)):
            cols[f"{v}_{name}"] = np.array([np.nan, np.nan, val])
    cols["bitso_mxn_gap"] = np.array([np.nan, np.nan, 0.001])
    cols["close"] = np.array([1.3, 1.3, 1.3])
    return bot, w, Ctx(ts, 2, w, {RAIL: cols}, H)


def test_xrp_rail_books_a_real_spread_net_of_all_costs():
    bot, w, ctx = rail_ctx({"bitso": (1.3190, 1.3200, 50_000, 50_000), "binance": (1.3400, 1.3401, 50_000, 50_000),
                            "kucoin": (1.3350, 1.3352, 50_000, 50_000)})
    bot.on_bar(ctx)
    gross = 1.3400 / 1.3200 - 1
    net = gross - 0.0036 - 0.0010 - 2 * 0.0005
    assert bot.st["opps"] == 1 and bot.st["best_net"] == pytest.approx(net)
    assert w.realized_pnl == pytest.approx(300 * net, rel=1e-9)                  # tamaño = 30% del capital del bot
    assert w.fees_paid == pytest.approx(300 * (0.0036 + 0.0010))
    assert w.equity({}) == pytest.approx(w.initial_cash + w.realized_pnl)
    (f,) = w.drain_extra_fills()
    assert f.kind == "arb" and f.reason == "bitso->binance"


def test_xrp_rail_ignores_spreads_that_do_not_cover_fees():
    # un spread bruto de 0.40% es una "oportunidad" visual, pero Bitso cobra 0.36% + 0.10% + slippage
    bot, w, ctx = rail_ctx({"bitso": (1.3290, 1.3300, 50_000, 50_000), "binance": (1.3353, 1.3354, 50_000, 50_000)})
    bot.on_bar(ctx)
    assert bot.st["samples"] == 1 and bot.st["opps"] == 0 and bot.st["best_net"] < 0
    assert w.realized_pnl == 0 and w.drain_extra_fills() == []


def test_xrp_rail_does_nothing_without_a_snapshot():
    bot, w, ctx = rail_ctx({})
    bot.on_bar(ctx)
    assert bot.st["samples"] == 0
    bot, w, ctx = rail_ctx({"binance": (1.3, 1.3001, 1e5, 1e5), "kucoin": (1.3, 1.3001, 1e5, 1e5)})   # sin Bitso: no cuenta
    bot.on_bar(ctx)
    assert bot.st["samples"] == 0


def test_xrp_rail_rebalances_when_inventory_drifts_and_charges_for_it():
    q = {"bitso": (1.3190, 1.3200, 50_000, 50_000), "binance": (1.3400, 1.3401, 50_000, 50_000)}
    bot, w, ctx = rail_ctx(q)
    bot.on_bar(ctx)
    ctx2 = Ctx(3 * H, 2, w, ctx.arrays, H)
    bot.on_bar(ctx2)                                      # 2º trade: el inventario por venue supera 35% del capital
    kinds = [(f.side, f.reason) for f in w.drain_extra_fills()]
    assert ("buy", "rebalance_xrp_rail") in kinds and bot.st["rebalances"] == 1 and bot.st["inv"] == {}


def test_xrp_rail_respects_book_depth():
    q = {"bitso": (1.3190, 1.3200, 50_000, 100.0), "binance": (1.3400, 1.3401, 50_000, 50_000)}   # solo 100 XRP en la punta
    bot, w, ctx = rail_ctx(q)
    bot.on_bar(ctx)
    (f,) = w.drain_extra_fills()
    assert f.qty == pytest.approx(100.0)                  # no puede operar más de lo que ofrece la punta del libro


# =============================================================================== fuentes de datos
KLINES = {"code": "200000", "data": [[1792094400000, 82345.5, 82412.5, 81903.6, 82063.5, 82359, 6766443.5839],
                                     [1792098000000, 82077.0, 82424.9, 81976.2, 82100.0, 7000, 5.0]]}
FUNDING = {"code": "200000", "data": [{"symbol": "XBTUSDTM", "fundingRate": 5.7E-5, "timepoint": 1792108800000},
                                      {"symbol": "XBTUSDTM", "fundingRate": 7.4E-5, "timepoint": 1792080000000}]}


def test_kucoin_parsers_match_the_real_api_shape():
    k = parse_kucoin_futures_klines(KLINES)
    assert list(k.columns) == ["open", "high", "low", "close", "volume"] and k.index.dtype == "int64"
    assert k.iloc[0].open == 82345.5 and k.iloc[0].high == 82412.5 and k.iloc[0].low == 81903.6 and k.iloc[0].close == 82063.5
    assert (k.high >= k[["open", "close"]].max(axis=1)).all() and (k.low <= k[["open", "close"]].min(axis=1)).all()
    f = parse_kucoin_funding(FUNDING)
    assert f == {1792108800000: 5.7e-5, 1792080000000: 7.4e-5}
    assert simdata.kucoin_contract("BTCUSDT~PERP") == "XBTUSDTM" and simdata.kucoin_contract("ETHUSDT~PERP") == "ETHUSDTM"
    assert parse_kucoin_futures_klines({"data": []}).empty


class _Resp:
    def __init__(self, payload, status=200):
        self.payload, self.status_code, self.headers = payload, status, {}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


class _FakeSession:
    """Sirve las respuestas con el mismo formato que las APIs reales (verificadas desde GitHub Actions el 2026-10-16)."""
    def __init__(self, bitso_down=False):
        self.calls, self.bitso_down = [], bitso_down

    def get(self, url, params=None, timeout=None):
        params = params or {}
        self.calls.append((url, dict(params)))
        if "kline/query" in url:
            a, b = params["from"] // H * H, params["to"] // H * H
            assert params["granularity"] == 60 and (b - a) // H <= 200, "paginación: máx. 200 velas por llamada"
            rows = [[t, 100.0, 101.0, 99.0, 100.5, 10.0, 1000.0] for t in range(a, b + H, H)]
            return _Resp({"code": "200000", "data": rows})
        if "funding-rates" in url:
            a, b = params["from"], params["to"]
            return _Resp({"code": "200000", "data": [
                {"symbol": params["symbol"], "fundingRate": 1e-4, "timepoint": t}
                for t in range((a // (8 * H) + 1) * 8 * H, b, 8 * H)][::-1]})                  # la API los devuelve del más nuevo al más viejo
        if "bitso.com" in url:
            if self.bitso_down:
                return _Resp({}, 500)
            book = params.get("book")
            if "order_book" in url:
                return _Resp({"success": True, "payload": {"bids": [{"price": "1.3356", "amount": "5000"}],
                                                          "asks": [{"price": "1.3359", "amount": "7000"}]}})
            t = {"xrp_usdt": ("1.335570", "1.335890"), "xrp_mxn": ("24.6042", "24.6047"), "usdt_mxn": ("18.40", "18.42")}[book]
            return _Resp({"success": True, "payload": {"bid": t[0], "ask": t[1], "book": book}})
        if "bookTicker" in url:
            return _Resp({"symbol": "XRPUSDT", "bidPrice": "1.33560000", "bidQty": "23402.5", "askPrice": "1.33570000", "askQty": "36258.7"})
        if "level1" in url:
            return _Resp({"code": "200000", "data": {"bestBid": "1.3355", "bestBidSize": "900", "bestAsk": "1.3358", "bestAskSize": "800"}})
        raise AssertionError(f"URL inesperada: {url}")


def _feed(tmp_path, **kw):
    f = MarketFeed(cache_dir=tmp_path / "c", pause=0)
    f.session = _FakeSession(**kw)
    return f


def test_market_feed_builds_the_perp_frame_with_funding(tmp_path):
    f = _feed(tmp_path)
    df = f.latest_closed("BTCUSDT~PERP", "1h", 700)
    now = int(time.time() * 1000)
    assert len(df) >= 690 and (df.index + H <= now).all(), "solo velas cerradas"
    assert df.index.is_monotonic_increasing and not df.index.duplicated().any()
    hours = (df.index // H) % 8
    assert df.funding[hours == 0].notna().sum() > 80 and df.funding[hours != 0].isna().all()
    assert max(c[1]["to"] - c[1]["from"] for c in f.session.calls if "kline" in c[0]) <= 200 * H


def test_market_feed_rail_snapshot_and_graceful_degradation(tmp_path):
    f = _feed(tmp_path)
    snap = f.rail_snapshot()
    assert snap["bitso_bid"] == pytest.approx(1.33557) and snap["bitso_aq"] == 7000 and snap["binance_bq"] == 23402.5
    assert snap["kucoin_ask"] == 1.3358
    mid_mxn = (24.6042 + 24.6047) / 2 / ((18.40 + 18.42) / 2)
    assert snap["bitso_mxn_gap"] == pytest.approx(mid_mxn / ((1.3356 + 1.3357) / 2) - 1)
    real_sleep = simdata.time.sleep
    simdata.time.sleep = lambda s: None
    try:
        g = _feed(tmp_path, bitso_down=True)
        s2 = g.rail_snapshot()
    finally:
        simdata.time.sleep = real_sleep
    assert np.isnan(s2["bitso_bid"]) and s2["binance_bid"] == 1.3356 and s2["kucoin_bid"] == 1.3355   # Bitso caído: el resto sigue


def test_rail_frame_has_the_snapshot_only_on_the_last_bar(tmp_path):
    f = _feed(tmp_path)
    base = df_from(np.full(50, 1.33))
    base.index = base.index + (int(time.time() * 1000) // H - 60) * H
    df = f._rail_frame(base)
    assert df.binance_bid.iloc[-1] == 1.3356 and df.binance_bid.iloc[:-1].isna().all()
    assert set(simdata.rail_snapshot_columns()) <= set(df.columns)


# =============================================================================== guardas del modo nube
def test_changing_the_bot_config_midway_is_refused(tmp_path):
    cfgs = copy.deepcopy(config.BOTS)
    code, st = run_step(cfgs, "1h", CAP, None, str(tmp_path / "a"), "synthetic", synthetic_advance=24)
    assert code == 0, st
    cfgs[1]["params"]["entry_dev"] = 0.0010                     # "afinar" un parámetro a mitad de la prueba
    code, st = run_step(cfgs, "1h", CAP, str(tmp_path / "a" / "ledger.json"), str(tmp_path / "b"), "synthetic", synthetic_advance=24)
    assert code == 1 and "configuración" in st["message"] and "fresh" in st["message"]
    assert not (tmp_path / "b" / "ledger.json").exists()


def test_portfolio_allocation_matches_the_glossary():
    glossary = {"b01_carry": 0.15, "b02_stable": 0.15, "b03_dca": 0.08, "b04_grid": 0.12, "b05_meanrev": 0.10,
                "b06_mm": 0.08, "b07_trend": 0.08, "b08_breakout": 0.07, "b09_ml": 0.05, "b10_xrp": 0.10}
    pct = {b["id"]: b["capital_pct"] for b in config.BOTS}
    assert sum(pct.values()) == pytest.approx(1.0)                        # arranca con el 100 % de los 10,000 USDT
    for k, v in glossary.items():
        assert pct[k] == pytest.approx(v / 0.98)                          # pesos relativos del glosario intactos
    assert sum(b["capital_pct"] * config.PORTFOLIO_CAPITAL for b in config.BOTS) == pytest.approx(10_000.0)
