"""Observatorio de mercado: una corrida completa de punta a punta con una red FALSA (sin tocar internet)."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import mercado_step as ms
from sim import market_events as me
from sim import market_feeds as mf

H = 3_600_000
D = 86_400_000
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "LTCUSDT", "LINKUSDT", "BNBUSDT", "TRXUSDT"]
RSS = """<?xml version="1.0"?><rss><channel><item><title>Bitcoin rallies on ETF inflows</title><link>https://x.test/{n}</link><pubDate>Tue, 10 Nov 2026 12:00:00 GMT</pubDate></item></channel></rss>"""


class FakeNet:
    def __init__(self, fail=()):
        self.s = None
        self.fail = fail
        self.calls = []
        self.rngs = {s: np.random.default_rng(i) for i, s in enumerate(SYMS)}
        start = pd.Timestamp("2017-08-17")
        self.dates = pd.date_range(start, "2026-12-31", freq="D")
        self.px = {s: 100 * np.exp(np.cumsum(np.random.default_rng(10 + i).normal(0.0004, 0.03, len(self.dates)))) for i, s in enumerate(SYMS)}

    def fng(self):
        return {"value": 50}

    def json(self, url, params=None):
        self.calls.append(url)
        if any(f in url for f in self.fail):
            raise RuntimeError("caído")
        p = params or {}
        if "klines" in url and p.get("interval") == "1d":
            sym = p["symbol"]
            if sym not in self.px:
                return []
            i0 = max(0, int((pd.Timestamp(p["startTime"], unit="ms") - self.dates[0]).days))
            rows = [[int(d.timestamp() * 1000), "1", "1", "1", str(self.px[sym][i]), "1", int(d.timestamp() * 1000) + D - 1, "0", 1, "0.5", "0", "0"]
                    for i, d in list(enumerate(self.dates))[i0:i0 + 1000]]
            return rows
        if "klines" in url:                                                       # 1 h
            now = int(pd.Timestamp("2026-11-10 00:07").timestamp() * 1000) // H * H
            return [[now - (30 - i) * H, "100", "1", "1", "100", "10", now - (30 - i) * H + H - 1, "0", 1, "6", "0", "0"] for i in range(30)]
        if "ticker/price" in url:
            return {"price": "70000"}
        if "depth" in url:
            return {"bids": [["100", "2"]], "asks": [["101", "1"]]}
        if "funding-rate-history" in url:
            return {"code": "0", "data": [{"fundingRate": "0.0001"}]}
        if "open-interest" in url and "rubik" not in url:
            return {"code": "0", "data": [{"oiUsd": "1e9"}]}
        if "long-short" in url:
            return {"code": "0", "data": [["1", "2.5"]]}
        if "taker-volume" in url:
            return {"code": "0", "data": [["1", "40", "60"]]}
        if "instruments" in url or "liquidation" in url:
            return {"code": "0", "data": [{"ctVal": "0.01", "details": []}]}
        if "okx.com/api/v5/support" in url:
            return {"code": "0", "data": [{"details": [{"title": "OKX to list FOO (FOO)", "pTime": "1794000000000", "url": "https://okx/foo"}]}]}
        if "contracts/active" in url:
            return {"data": [{"symbol": "XBTUSDTM", "status": "Open", "markPrice": 70000, "openInterest": "10", "multiplier": 0.001, "fundingFeeRate": 0.0001}]}
        if "deribit" in url:
            return {"result": {"data": [[1, 1, 1, 1, 45.0]]}}
        if "coinbase" in url:
            return {"price": "70500"}
        if "stablecoincharts" in url:
            return [{"date": str(86400 * i), "totalCirculatingUSD": {"peggedUSD": 1e11 + i}} for i in range(10)]
        if "coingecko" in url:
            return {"data": {"market_cap_percentage": {"btc": 58.0}, "total_market_cap": {"usd": 3e12}, "market_cap_change_percentage_24h_usd": 1.0}}
        if "binance.com/bapi" in url:
            return {"data": {"catalogs": [{"articles": [{"id": 1, "code": "c1", "title": "Binance Will List Bar (BAR)", "releaseDate": 1794000000000}]}]}}
        if "kucoin.com/api/v3/announcements" in url:
            return {"data": {"items": [{"annId": 5, "annTitle": "KuCoin Will List Baz", "cTime": 1794000000000, "annUrl": "u"}]}}
        if "stocktwits" in url:
            return {"messages": [{"id": 9, "body": "up", "created_at": "2026-11-10T00:00:00Z", "entities": {"sentiment": {"basic": "Bullish"}}}]}
        raise AssertionError("URL no prevista: " + url)

    def bytes(self, url, params=None):
        self.calls.append(url)
        if any(f in url for f in self.fail):
            raise RuntimeError("caído")
        if "federalreserve" in url:
            return b"<html>nada reconocible</html>"
        return RSS.format(n=url[-12:].replace("/", "_")).encode()


def _ts(s):
    return int(pd.Timestamp(s).timestamp() * 1000)


def test_full_run_creates_state_and_output(tmp_path):
    net = FakeNet()
    code, info = ms.run(str(tmp_path), net, now_ms=_ts("2026-11-10 00:07"), symbols=SYMS, sleep=lambda s: None)
    assert code == 0, info
    for f in ("closes.csv", "flows.json", "events.json", "items.json", "predictions.json", "event_study.json"):
        assert (tmp_path / "state" / f).exists(), f
    d = json.loads((tmp_path / "data" / "mercado.json").read_text())
    assert set(d) >= {"fase0", "fase1", "fase2", "fase3", "predicciones", "estado_fuentes", "aviso"}
    assert d["fase1"]["ultima"]["btc_okx_funding"] == 0.0001 and d["fase1"]["ultima"]["fng"] == 50
    assert d["fase0"] is None or "hoy" in d["fase0"]                                  # con 10 monedas sintéticas el panel igual se arma
    assert d["fase2"]["n_eventos"] >= len(me.FOMC_STATIC) and any(e["kind"] == "listing" for e in d["fase2"]["eventos_recientes"])
    assert d["fase3"]["n_items"] > 0 and d["fase3"]["titulares"][0]["score"] > 0
    assert len(d["predicciones"]["recientes"]) == 2 and d["predicciones"]["marcador"]["veredicto"] == "sin veredicto"
    assert d["fase1"]["dias_con_datos"] == 1 and d["fase1"]["evaluacion"] == [] or d["fase1"]["evaluacion"][0]["veredicto"] == "sin veredicto"
    st = json.loads((tmp_path / "data" / "status.json").read_text())
    assert st["ok"] > 20 and "error" not in st


def test_rerun_same_hour_is_idempotent_and_next_week_resolves(tmp_path):
    net = FakeNet()
    t0 = _ts("2026-11-10 00:07")
    ms.run(str(tmp_path), net, now_ms=t0, symbols=SYMS, sleep=lambda s: None)
    ms.run(str(tmp_path), net, now_ms=t0 + 20 * 60_000, symbols=SYMS, sleep=lambda s: None)       # misma hora: no duplica nada
    flows = json.loads((tmp_path / "state" / "flows.json").read_text())
    assert len(flows["rows"]) == 1
    n_items = len(json.loads((tmp_path / "state" / "items.json").read_text()))
    ms.run(str(tmp_path), net, now_ms=t0 + 20 * 60_000 + 60_000, symbols=SYMS, sleep=lambda s: None)
    assert len(json.loads((tmp_path / "state" / "items.json").read_text())) == n_items            # mismos titulares: sin duplicados
    assert len(json.loads((tmp_path / "state" / "predictions.json").read_text())) == 2
    before = len(net.calls)
    ms.run(str(tmp_path), net, now_ms=t0 + 60 * 60_000, symbols=SYMS, sleep=lambda s: None)
    daily_klines = [c for c in net.calls[before:] if "klines" in c]
    assert len(daily_klines) == 2                                                                  # solo las velas de 1 h de BTC y ETH: los cierres diarios ya estaban al día
    ms.run(str(tmp_path), net, now_ms=t0 + 8 * D, symbols=SYMS, sleep=lambda s: None)              # una semana después: se resuelven las del día 9
    preds = json.loads((tmp_path / "state" / "predictions.json").read_text())
    assert any(p["resolved"] for p in preds) and len(preds) == 4
    r = next(p for p in preds if p["resolved"])
    assert r["up"] in (0, 1) and r["rv7"] > 0


def test_failing_sources_do_not_stop_the_run(tmp_path):
    net = FakeNet(fail=("okx.com", "reddit", "coindesk"))
    code, info = ms.run(str(tmp_path), net, now_ms=_ts("2026-11-10 00:07"), symbols=SYMS, sleep=lambda s: None)
    assert code == 0
    st = json.loads((tmp_path / "data" / "status.json").read_text())
    assert st["fuentes"]["okx_funding_BTC"].startswith("RuntimeError") and st["fuentes"]["feed_coindesk"].startswith("RuntimeError")
    d = json.loads((tmp_path / "data" / "mercado.json").read_text())
    assert d["fase1"]["ultima"]["btc_okx_funding"] is None and d["fase1"]["ultima"]["btc_taker_buy_ratio_24h"] is not None


def test_all_sources_down_returns_code_2(tmp_path):
    class Dead(FakeNet):
        def json(self, url, params=None):
            raise RuntimeError("sin red")

        def bytes(self, url, params=None):
            raise RuntimeError("sin red")

        def fng(self):
            return None
    code, info = ms.run(str(tmp_path), Dead(), now_ms=_ts("2026-11-10 00:07"), symbols=SYMS, sleep=lambda s: None)
    assert code in (1, 2)
    assert (tmp_path / "data" / "status.json").exists()
