"""Sondeo (solo lectura) para el backtest 2019-2024: ¿qué historial alcanzan los runners de GitHub Actions?
Imprime un resumen compacto por fuente. No guarda datos ni toma decisiones."""
import json, re, sys, time
import requests

S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 (probe)"
def ms(d): return int(__import__("pandas").Timestamp(d, tz="UTC").timestamp() * 1000)
def show(name, fn):
    t0 = time.time()
    try:
        out = fn()
    except Exception as e:
        out = f"ERROR {type(e).__name__}: {str(e)[:160]}"
    print(f"[{name}] {out}  ({time.time()-t0:.1f}s)", flush=True)

def spot(sym, d0, d1, interval="1h", base="https://data-api.binance.vision"):
    r = S.get(base + "/api/v3/klines", params=dict(symbol=sym, interval=interval, startTime=ms(d0), endTime=ms(d1), limit=1000), timeout=30)
    if r.status_code != 200: return f"HTTP {r.status_code} {r.text[:80]}"
    j = r.json(); return f"{len(j)} velas, primera {__import__('pandas').Timestamp(j[0][0],unit='ms') if j else None}"

def head(url):
    r = S.head(url, timeout=30, allow_redirects=True); return f"HTTP {r.status_code} len={r.headers.get('content-length')}"

print("== Spot Binance (API data-api.binance.vision) ==")
for sym, d0, d1 in [("BTCUSDT","2019-01-01","2019-01-10"),("ETHUSDT","2019-01-01","2019-01-10"),("USDCUSDT","2019-01-01","2019-01-10"),
                    ("EOSUSDT","2019-01-01","2019-01-10"),("XMRUSDT","2019-01-01","2019-01-10"),("BSVUSDT","2019-12-01","2019-12-10"),
                    ("LUNAUSDT","2022-04-01","2022-04-10"),("FTTUSDT","2022-10-01","2022-10-10"),("UNIUSDT","2020-09-20","2020-09-30"),
                    ("XMRUSDT","2024-01-01","2024-01-10"),("FDUSDUSDT","2023-06-01","2023-06-10"),("TUSDUSDT","2019-01-01","2019-01-10")]:
    show(f"spot {sym} {d0}", lambda sym=sym,d0=d0,d1=d1: spot(sym,d0,d1))
print("== Archivo data.binance.vision (spot mensual 1h) ==")
for sym, ym in [("LUNAUSDT","2022-04"),("FTTUSDT","2022-10"),("XMRUSDT","2023-06"),("BTCUSDT","2019-01"),("BSVUSDT","2019-12")]:
    show(f"zip {sym} {ym}", lambda sym=sym,ym=ym: head(f"https://data.binance.vision/data/spot/monthly/klines/{sym}/1h/{sym}-1h-{ym}.zip"))
print("== Perpetuo y funding ==")
show("binance fapi funding BTC 2020", lambda: (lambda r: f"HTTP {r.status_code} {r.text[:100]}")(S.get("https://fapi.binance.com/fapi/v1/fundingRate", params=dict(symbol="BTCUSDT", startTime=ms("2020-01-01"), limit=3), timeout=30)))
for sym, ym in [("BTCUSDT","2019-12"),("BTCUSDT","2020-01"),("ETHUSDT","2020-01")]:
    show(f"zip um funding {sym} {ym}", lambda sym=sym,ym=ym: head(f"https://data.binance.vision/data/futures/um/monthly/fundingRate/{sym}/{sym}-fundingRate-{ym}.zip"))
    show(f"zip um klines 1h {sym} {ym}", lambda sym=sym,ym=ym: head(f"https://data.binance.vision/data/futures/um/monthly/klines/{sym}/1h/{sym}-1h-{ym}.zip"))
for sym in ("XBTUSDTM","ETHUSDTM"):
    for d0 in ("2019-06-01","2020-06-01","2021-01-01","2021-06-01"):
        def k(sym=sym,d0=d0):
            r = S.get("https://api-futures.kucoin.com/api/v1/kline/query", params=dict(symbol=sym, granularity=60, **{"from":ms(d0),"to":ms(d0)+5*3600000}), timeout=30)
            j = r.json(); return f"HTTP {r.status_code} velas={len(j.get('data') or [])} code={j.get('code')}"
        show(f"kucoin kline {sym} {d0}", k)
        def f(sym=sym,d0=d0):
            r = S.get("https://api-futures.kucoin.com/api/v1/contract/funding-rates", params=dict(symbol=sym, **{"from":ms(d0),"to":ms(d0)+20*86400000}), timeout=30)
            j = r.json(); return f"HTTP {r.status_code} funding={len(j.get('data') or [])}"
        show(f"kucoin funding {sym} {d0}", f)
print("== Capitalización histórica ==")
def cmc(d):
    r = S.get(f"https://coinmarketcap.com/historical/{d}/", timeout=40)
    m = re.search(r'__NEXT_DATA__[^>]*>(.*?)</script>', r.text, re.S)
    n = len(re.findall(r'"slug"', r.text))
    return f"HTTP {r.status_code} bytes={len(r.text)} next_data={'sí' if m else 'no'} slugs={n}"
for d in ("20190106","20200105","20220102"):
    show(f"cmc historical {d}", lambda d=d: cmc(d))
show("coingecko history BTC 2019", lambda: (lambda r: f"HTTP {r.status_code} {r.text[:120]}")(S.get("https://api.coingecko.com/api/v3/coins/bitcoin/history", params=dict(date="01-01-2019"), timeout=30)))
