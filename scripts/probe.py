"""Sondeo de red: ¿qué APIs públicas alcanza este servidor? (solo lectura, sin llaves).
Escribe probe_results.json. Se usa una vez para decidir qué fuentes de datos puede consumir el simulador."""
import json
import sys
import time

import requests

NOW = int(time.time() * 1000)
H = 3_600_000
TESTS = {
    "binance_spot_usdcusdt": "https://data-api.binance.vision/api/v3/klines?symbol=USDCUSDT&interval=1h&limit=3",
    "binance_spot_fdusdusdt": "https://data-api.binance.vision/api/v3/klines?symbol=FDUSDUSDT&interval=1h&limit=3",
    "binance_spot_xrpusdt": "https://data-api.binance.vision/api/v3/klines?symbol=XRPUSDT&interval=1h&limit=3",
    "binance_bookticker_xrp": "https://data-api.binance.vision/api/v3/ticker/bookTicker?symbol=XRPUSDT",
    "binance_fapi_funding": "https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=3",
    "binance_fapi_klines": "https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1h&limit=3",
    "binance_fapi_premium": "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT",
    "okx_funding_hist": "https://www.okx.com/api/v5/public/funding-rate-history?instId=BTC-USDT-SWAP&limit=3",
    "okx_swap_candles": "https://www.okx.com/api/v5/market/history-candles?instId=BTC-USDT-SWAP&bar=1H&limit=3",
    "okx_spot_candles": "https://www.okx.com/api/v5/market/history-candles?instId=BTC-USDT&bar=1H&limit=3",
    "kucoin_spot_candles": "https://api.kucoin.com/api/v1/market/candles?type=1hour&symbol=BTC-USDT",
    "kucoin_fut_funding": f"https://api-futures.kucoin.com/api/v1/contract/funding-rates?symbol=XBTUSDTM&from={NOW - 48 * H}&to={NOW}",
    "kucoin_fut_klines": f"https://api-futures.kucoin.com/api/v1/kline/query?symbol=XBTUSDTM&granularity=60&from={NOW - 5 * H}&to={NOW}",
    "bybit_funding": "https://api.bybit.com/v5/market/funding/history?category=linear&symbol=BTCUSDT&limit=3",
    "bitso_books": "https://api.bitso.com/v3/available_books/",
    "bitso_xrp_mxn": "https://api.bitso.com/v3/ticker/?book=xrp_mxn",
    "bitso_usdt_mxn": "https://api.bitso.com/v3/ticker/?book=usdt_mxn",
    "bitso_xrp_usd": "https://api.bitso.com/v3/ticker/?book=xrp_usd",
    "bitso_xrp_usdt": "https://api.bitso.com/v3/ticker/?book=xrp_usdt",
    "bitso_usd_mxn": "https://api.bitso.com/v3/ticker/?book=usd_mxn",
}
out = {}
for name, url in TESTS.items():
    t0 = time.time()
    try:
        r = requests.get(url, timeout=20)
        body = r.text
        out[name] = {"status": r.status_code, "ms": int((time.time() - t0) * 1000), "bytes": len(body),
                     "head": body[:300] if name != "bitso_books" else body[:200]}
        if name == "bitso_books" and r.ok:
            books = r.json().get("payload", [])
            out[name]["books_xrp_usdt_related"] = [b for b in books if any(k in b["book"] for k in ("xrp", "usdt", "usd_mxn"))]
    except Exception as e:
        out[name] = {"status": None, "error": f"{type(e).__name__}: {e}"[:300]}
    print(name, out[name].get("status"), out[name].get("error", ""), flush=True)
with open("probe_results.json", "w", encoding="utf-8") as f:
    json.dump(out, f, indent=1, ensure_ascii=False)
