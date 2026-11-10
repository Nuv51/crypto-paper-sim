"""Observatorio de mercado, fases 1-3: parsers de fuentes, anuncios/calendario, texto y tono, evaluación y predicciones (sin red)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sim import market_eval as ev
from sim import market_events as me
from sim import market_feeds as mf
from sim import market_pred as mp
from sim import market_text as mt

H = 3_600_000
NOW = 1_794_100_000_000 // H * H + 7 * 60_000          # ≈ minuto 7 de una hora


# ----------------------------------------------------------------------------- fase 1
def _klines(n, start, taker_share=0.6, vol=10.0):
    rows = []
    for i in range(n):
        t = start + i * H
        rows.append([t, "100", "101", "99", str(100 + i), str(vol), t + H - 1, "0", 5, str(vol * taker_share), "0", "0"])
    return rows


def test_binance_taker_ratio_uses_closed_bars_only():
    rows = _klines(30, NOW - 30 * H, 0.6)
    rows[-1][5], rows[-1][9] = "10", "0"                    # la última vela aún no cierra (cierra después de NOW) → se ignora
    rows[-1][6] = NOW + H
    r = mf.parse_binance_taker_ratio(rows, NOW)
    assert abs(r["ratio"] - 0.6) < 1e-9 and r["price"] > 100
    assert mf.parse_binance_taker_ratio(rows[:10], NOW) is None


def test_book_imbalance_and_cover():
    book = {"bids": [["100", "3"], ["99.9", "3"]], "asks": [["100.1", "1"], ["100.2", "1"]]}
    r = mf.parse_book_imbalance(book)
    assert 0.45 < r["imb"] < 0.55 and 0 < r["cover_pct"] < 0.01
    assert mf.parse_book_imbalance({"bids": [], "asks": []}) is None


def test_okx_parsers_and_error_code():
    assert mf.parse_okx_funding({"code": "0", "data": [{"fundingRate": "0.0001"}]}) == 0.0001
    assert mf.parse_okx_open_interest_usd({"code": "0", "data": [{"oiUsd": "5e9"}]}) == 5e9
    assert mf.parse_okx_open_interest_usd({"code": "0", "data": [{"oiCcy": "100"}]}, price=50.0) == 5000.0
    assert mf.parse_okx_latest_pair({"code": "0", "data": [["1", "3.17"], ["0", "3.1"]]}) == 3.17
    assert abs(mf.parse_okx_taker_buy_ratio({"code": "0", "data": [["1", "300", "700"]]}) - 0.7) < 1e-12
    try:
        mf.parse_okx_funding({"code": "50011", "msg": "rate limit", "data": []})
        assert False
    except ValueError:
        pass


def test_okx_liquidations_sides():
    p = {"code": "0", "data": [{"details": [
        {"posSide": "long", "side": "sell", "sz": "100", "bkPx": "70000", "ts": "1000"},
        {"posSide": "short", "side": "buy", "sz": "50", "bkPx": "70000", "ts": "2000"},
        {"posSide": "net", "side": "sell", "sz": "10", "bkPx": "70000", "ts": "3000"}]}]}
    r = mf.parse_okx_liquidations(p, 0.01)
    assert r["n"] == 3 and abs(r["long_usd"] - (100 + 10) * 0.01 * 70000) < 1e-6 and abs(r["short_usd"] - 50 * 0.01 * 70000) < 1e-6


def test_kucoin_deribit_llama_gecko():
    kc = mf.parse_kucoin_contracts({"data": [{"symbol": "XBTUSDTM", "status": "Open", "markPrice": 70000, "openInterest": "1000", "multiplier": 0.001,
                                               "fundingFeeRate": 0.0001, "turnoverOf24h": 5e8},
                                              {"symbol": "XBTUSDM", "status": "Open"}]})
    assert set(kc) == {"BTC"} and abs(kc["BTC"]["oi_usd"] - 70000 * 1000 * 0.001) < 1e-6
    assert mf.parse_deribit_dvol({"result": {"data": [[1, 1, 1, 1, 40.0], [2, 1, 1, 1, 41.5]]}}) == 41.5
    rows = [{"date": str(86400 * i), "totalCirculatingUSD": {"peggedUSD": 100 + i}} for i in range(10)]
    r = mf.parse_llama_stable_total(rows)
    assert r["total"] == 109 and abs(r["chg_7d"] - (109 / 102 - 1)) < 1e-12
    assert mf.parse_llama_stable_total(rows[:3]) is None
    g = mf.parse_gecko_global({"data": {"market_cap_percentage": {"btc": 58.2}, "total_market_cap": {"usd": 3e12}, "market_cap_change_percentage_24h_usd": -1.5}})
    assert g["btc_dominance"] == 58.2 and g["mcap_chg_24h"] == -1.5


def test_collect_flows_survives_a_failing_source():
    def get(url, params=None):
        if "klines" in url:
            return _klines(30, NOW - 30 * H)
        if "depth" in url:
            return {"bids": [["100", "2"]], "asks": [["101", "1"]]}
        if "okx.com" in url and "funding" in url:
            raise RuntimeError("OKX caído")
        if "okx.com" in url:
            return {"code": "0", "data": [{"oiUsd": "1e9", "details": []}]}
        if "contracts/active" in url:
            return {"data": [{"symbol": "XBTUSDTM", "status": "Open", "markPrice": 70000, "openInterest": "10", "multiplier": 0.001, "fundingFeeRate": 0.0001}]}
        if "deribit" in url:
            return {"result": {"data": [[1, 1, 1, 1, 40.0]]}}
        if "coinbase" in url:
            return {"price": "70700"}
        if "stablecoincharts" in url:
            return [{"date": str(86400 * i), "totalCirculatingUSD": {"peggedUSD": 1e11 + i}} for i in range(10)]
        if "coingecko" in url:
            return {"data": {"market_cap_percentage": {"btc": 58.0}, "total_market_cap": {"usd": 3e12}, "market_cap_change_percentage_24h_usd": 1.0}}
        raise AssertionError(url)

    row, st, kc = mf.collect_flows(now_ms=NOW, get=get, fng_fn=lambda: {"value": 55})
    assert row["ts"] == NOW // H * H and set(row) == set(mf.FLOW_COLUMNS)
    assert row["btc_okx_funding"] is None and st["okx_funding_BTC"].startswith("RuntimeError")
    assert st["binance_taker_BTC"] == "ok" and abs(row["btc_taker_buy_ratio_24h"] - 0.6) < 1e-9
    assert row["btc_okx_oi_usd"] == 1e9 and row["btc_kc_funding"] == 0.0001 and row["btc_dvol"] == 40.0
    assert abs(row["btc_coinbase_premium"] - (70700 / row["btc_price"] - 1)) < 1e-12
    assert row["fng"] == 55 and row["btc_dominance"] == 58.0 and "BTC" in kc


# ----------------------------------------------------------------------------- fase 2
def test_announcement_parsers_and_symbols():
    b = me.parse_binance_cms({"data": {"catalogs": [{"articles": [
        {"id": 1, "code": "abc123", "title": "Binance Will List Foo (FOO) with Seed Tag Applied", "releaseDate": 1_794_000_000_000},
        {"id": 2, "code": "xyz9", "title": "Notice of Removal of Spot Trading Pairs - 2026-11-12", "releaseDate": 1_794_100_000_000}]}]}}, "listing")
    assert b[0]["id"] == "binance:abc123" and b[0]["kind"] == "listing" and b[0]["symbols"] == ["FOO"]
    assert b[1]["kind"] == "delisting"
    o = me.parse_okx_announcements({"code": "0", "data": [{"details": [
        {"title": "OKX to list BAR (BAR) for spot trading", "pTime": "1794000000000", "url": "https://www.okx.com/help/okx-to-list-bar"}]}]}, "listing")
    assert o[0]["symbols"] == ["BAR"] and o[0]["exchange"] == "okx"
    k = me.parse_kucoin_announcements({"data": {"items": [{"annId": 77, "annTitle": "KuCoin Will Delist BAZ", "cTime": 1794000000000, "annUrl": "u"}]}}, "delisting")
    assert k[0]["kind"] == "delisting" and k[0]["symbols"] == ["BAZ"]
    assert me.extract_symbols("The USDT market (USDT) and BTC") == []          # monedas base no cuentan


FOMC_HTML = """<div>2026 FOMC Meetings</div>
<div class="fomc-meeting__month col-xs-5"><strong>January</strong></div><div class="fomc-meeting__date col-xs-4">27-28</div>
<div class="fomc-meeting__month col-xs-5"><strong>March</strong></div><div class="fomc-meeting__date col-xs-4">17-18*</div>
<div>2025 FOMC Meetings</div>
<div class="fomc-meeting__month col-xs-5"><strong>December</strong></div><div class="fomc-meeting__date col-xs-4">9-10</div>"""


def test_fomc_parse_and_fallback_and_timestamp():
    days = me.parse_fomc_html(FOMC_HTML)
    assert days == ["2025-12-10", "2026-01-28", "2026-03-18"]
    evs = me.fomc_events(FOMC_HTML)                                  # la lectura no reproduce las 8 de 2026 → se ignora y se usa el calendario base
    assert len(evs) == len(me.FOMC_STATIC) and any(e["id"] == "fomc:2026-10-28" for e in evs)
    full = FOMC_HTML + "".join(f'<div class="fomc-meeting__month"><strong>{m}</strong></div><div class="fomc-meeting__date">{d}</div>'
                               for m, d in [("April", "28-29"), ("June", "16-17"), ("July", "28-29"), ("September", "15-16"), ("October", "27-28"), ("December", "8-9")])
    assert len(me.parse_fomc_html(full.replace("2025 FOMC Meetings", "2026 FOMC Meetings"))) >= 8
    e = next(e for e in me.fomc_events("") if e["id"] == "fomc:2026-10-28")
    assert pd.Timestamp(e["ts_pub"], unit="ms").hour == 18          # 14:00 de Nueva York en horario de verano = 18:00 UTC
    e2 = next(e for e in me.fomc_events("") if e["id"] == "fomc:2026-12-09")
    assert pd.Timestamp(e2["ts_pub"], unit="ms").hour == 19         # en invierno, 19:00 UTC


def test_merge_events_dedupes_and_keeps_old():
    a = {"id": "x:1", "ts_pub": 1, "title": "old"}
    store, n = me.merge_events([a], [{"id": "x:1", "ts_pub": 1, "title": "NEW"}, {"id": "x:2", "ts_pub": 2, "title": "t"}])
    assert n == 1 and [e["id"] for e in store] == ["x:1", "x:2"] and store[0]["title"] == "old"


def test_event_study_detects_planted_effect_and_null():
    idx = pd.date_range("2022-01-01", periods=900, freq="D")
    rng = np.random.default_rng(4)
    r = rng.normal(0, 0.02, len(idx))
    days = list(range(100, 860, 30))                                 # 26 eventos
    for d in days:
        r[d + 1] += 0.08                                             # sube 8 % el día siguiente al anuncio
    close = pd.Series(100 * np.exp(np.cumsum(r)), index=idx)
    events = [{"id": f"e{d}", "kind": "listing", "ts_pub": int(idx[d].timestamp() * 1000) + 3_600_000, "symbols": ["FOO"]} for d in days]
    res = me.event_study(events, {"FOO": close}, n_perm=500)
    w = res["ventanas"]["-1_+1"]
    assert w["n"] == 26 and w["mediana"] > 0.05 and w["p"] < 0.01
    assert me.study_verdict(w)[0] == "con evidencia"
    null = me.event_study([{**e, "ts_pub": e["ts_pub"] + 7 * 86_400_000 // 2 * 0} for e in events[:5]], {"FOO": close}, n_perm=50)
    assert me.study_verdict(null["ventanas"]["-1_+1"])[0] == "sin veredicto"        # <20 eventos
    assert me.event_study(events, {}, n_perm=10)["ventanas"]["-1_+1"]["sin_precio"] == 26    # sin precios: no se inventa nada


# ----------------------------------------------------------------------------- fase 3
RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Bitcoin surges to record high as ETF inflows jump</title><link>https://x.test/a</link><pubDate>Tue, 10 Nov 2026 12:00:00 GMT</pubDate><description>&lt;p&gt;Great&lt;/p&gt;</description></item>
<item><title>Exchange hacked, millions stolen</title><link>https://x.test/b</link><pubDate>Tue, 10 Nov 2026 13:00:00 GMT</pubDate></item></channel></rss>"""
ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Ethereum not crashing</title><link href="https://r.test/1"/><updated>2026-11-10T12:00:00+00:00</updated></entry></feed>"""


def test_feed_parsing_and_entity_rejection():
    it = mt.parse_feed(RSS, "coindesk", now_ms=5)
    assert len(it) == 2 and it[0]["url"] == "https://x.test/a" and it[0]["ts_pub"] > 0 and it[0]["summary"] == "Great" and it[0]["ts_seen"] == 5
    at = mt.parse_feed(ATOM, "reddit_Bitcoin", now_ms=5)
    assert at[0]["url"] == "https://r.test/1" and at[0]["ts_pub"] > 0
    try:
        mt.parse_feed('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaa">]><rss><channel/></rss>', "evil")
        assert False
    except ValueError:
        pass


def test_scoring_negation_assets_and_versions():
    assert mt.score_text("Bitcoin surges as ETF inflows jump") > 0.5
    assert mt.score_text("Exchange hacked, millions stolen") < -0.5
    assert mt.score_text("Ethereum not crashing") > 0                      # negación invierte
    assert mt.score_text("") == 0 and -1 <= mt.score_text("crash " * 20) <= 1
    assert mt.detect_assets("Solana and Bitcoin rally") == ["BTC", "SOL"] or set(mt.detect_assets("Solana and Bitcoin rally")) == {"BTC", "SOL"}
    its = mt.add_scores(mt.parse_feed(RSS, "coindesk", now_ms=5))
    assert its[0]["lex"] == mt.LEXICON_VERSION and "BTC" in its[0]["assets"]


def test_stocktwits_daily_tone_and_merge():
    now = int(pd.Timestamp("2026-11-10 09:00").timestamp() * 1000)
    st = mt.parse_stocktwits({"messages": [{"id": 1, "body": "moon", "created_at": "2026-11-10T08:00:00Z", "entities": {"sentiment": {"basic": "Bullish"}}},
                                           {"id": 2, "body": "rip", "created_at": "2026-11-10T08:01:00Z", "entities": {"sentiment": {"basic": "Bearish"}}},
                                           {"id": 3, "body": "hm", "created_at": "2026-11-10T08:02:00Z", "entities": {"sentiment": None}}]}, "BTC", now)
    news = mt.add_scores(mt.parse_feed(RSS, "coindesk", now_ms=now))
    store, n = mt.merge_items([], news + st)
    assert n == 5
    _, n2 = mt.merge_items(store, news + st)
    assert n2 == 0                                                          # misma publicación no se duplica
    d = mt.daily_tone(store)
    row = d.iloc[0]
    assert row["n"] == 2 and row["n_media"] == 2 and row["st_tagged"] == 2 and row["st_balance"] == 0.0
    assert abs(row["tone"] - np.mean([i["score"] for i in news])) < 1e-12


# ----------------------------------------------------------------------------- evaluación y predicciones
def test_partial_spearman_removes_control():
    rng = np.random.default_rng(1)
    z = rng.normal(size=500)
    x = z + rng.normal(scale=0.3, size=500)
    y = z + rng.normal(scale=0.3, size=500)
    raw, _ = ev.partial_spearman(y, x)
    part, _ = ev.partial_spearman(y, x, [z])
    assert raw > 0.7 and abs(part) < 0.2                                    # x e y solo se parecen por z


def test_evaluate_pair_verdicts():
    rng = np.random.default_rng(2)
    n = 400
    f = rng.normal(size=n)
    d = pd.DataFrame({"f": f, "ret7": 0.4 * f + rng.normal(size=n), "prior7": rng.normal(size=n)})
    r = ev.evaluate_pair(d, "f", "ret7", ["prior7"])
    assert r["veredicto"] == "aporta" and r["n_efectivo"] == n // 7
    d["ret7"] = rng.normal(size=n)
    assert ev.evaluate_pair(d, "f", "ret7", ["prior7"])["veredicto"] == "sin evidencia suficiente"
    assert ev.evaluate_pair(d.iloc[:60], "f", "ret7", ["prior7"])["veredicto"] == "sin veredicto"


def test_asset_frame_alignment_matches_hand_calculation():
    idx = pd.date_range("2026-01-01", periods=60, freq="D")
    c = pd.Series(100 * 1.01 ** np.arange(60), index=idx)
    f = ev.asset_frame(c)
    d = idx[20]
    assert abs(f.loc[d, "ret7"] - np.log(c.iloc[26] / c.iloc[19])) < 1e-12        # cierre[d+6] / cierre[d-1]
    assert abs(f.loc[d, "prior7"] - np.log(c.iloc[19] / c.iloc[12])) < 1e-12
    assert abs(f.loc[d, "rv7"] - np.sqrt(7) * np.log(1.01)) < 1e-9
    assert f["ret7"].iloc[-6:].isna().all()                                         # el futuro aún no existe


def test_predictions_lifecycle_and_score():
    idx = pd.date_range("2025-01-01", periods=520, freq="D")
    rng = np.random.default_rng(3)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0005, 0.02, len(idx)))), index=idx)
    preds = []
    for i in range(400, 500):
        d = idx[i]
        p = mp.make_prediction("BTC", close.loc[:d], str(d.date()), dvol=60.0)
        assert p and 0 <= p["p_up"] <= 1 and p["vol30"] > 0 and p["ewma"] > 0 and p["dvol"] > 0
        preds = mp.merge_predictions(preds, [p])
    assert len(mp.merge_predictions(preds, [preds[0]])) == 100                      # no se duplica
    assert mp.make_prediction("BTC", close.iloc[:50], "x") is None                  # sin historia suficiente
    n = mp.resolve(preds, {"BTCUSDT": close})
    assert n == 100 and all(p["resolved"] for p in preds)
    p0 = preds[0]
    assert abs(p0["ret7"] - np.log(close.loc[pd.Timestamp(p0["asof"]) + pd.Timedelta(days=7)] / close.loc[p0["asof"]])) < 1e-12
    s = mp.score(preds)
    a = s["por_activo"]["BTC"]
    assert s["veredicto"] == "evaluable" and a["n"] == 100 and set(a["vol"]) == {"vol30", "ewma", "dvol"} and a["brier"] > 0
    assert mp.score(preds[:10])["veredicto"] == "sin veredicto"
    # sin información del futuro: la frecuencia base de un día no depende de lo que pasa después
    c2 = close.copy(); c2.iloc[480:] *= 5
    assert mp.base_rate_up(close.iloc[:470]) == mp.base_rate_up(c2.iloc[:470])
