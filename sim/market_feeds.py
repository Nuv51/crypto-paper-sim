"""Observatorio de mercado · FASE 1: flujo de órdenes y derivados (solo lectura, sin llaves, sin operar).

Fuentes (todas verificadas desde GitHub Actions con scripts/probe_market.py; Binance Futures y Bybit están bloqueados):
  Binance spot (data-api.binance.vision) · OKX (derivados) · KuCoin Futures · Deribit (DVOL) · Coinbase · DefiLlama · CoinGecko · alternative.me
Cada función `parse_*` es pura (recibe el JSON, devuelve números) para poder probarla sin red; `collect_flows` junta una "foto" por hora.
Si una fuente falla, esa columna queda en None ese día y el motivo va a `status` (no se interpola ni se inventa).
Un dato es una FOTO tomada ahora (con su hora); nada se reconstruye con información posterior.
"""
from __future__ import annotations

import math
import time
from typing import Callable, Optional

import requests

from .data import _http_json, fetch_fear_greed

ASSETS = ("BTC", "ETH")
BINANCE = "https://data-api.binance.vision"
OKX = "https://www.okx.com"
KUCOIN_FUT = "https://api-futures.kucoin.com"
DERIBIT = "https://www.deribit.com"
COINBASE = "https://api.exchange.coinbase.com"
LLAMA = "https://stablecoins.llama.fi"
GECKO = "https://api.coingecko.com"
UA = {"User-Agent": "Mozilla/5.0 (compatible; crypto-paper-sim research; +https://github.com/Nuv51/crypto-paper-sim)"}
OKX_CTVAL_FALLBACK = {"BTC": 0.01, "ETH": 0.1}      # contratos de OKX: tamaño de un contrato en la moneda (se confirma en vivo si se puede)

FLOW_COLUMNS = (
    ["ts"]
    + [f"{a.lower()}_{k}" for a in ASSETS for k in (
        "price", "taker_buy_ratio_24h", "book_imb_top100", "okx_funding", "okx_oi_usd", "okx_ls_ratio", "okx_taker_buy_ratio_1h",
        "liq_long_usd", "liq_short_usd", "liq_n", "kc_funding", "kc_oi_usd", "dvol", "coinbase_premium")]
    + ["stable_total_usd", "stable_chg_7d", "btc_dominance", "total_mcap_usd", "mcap_chg_24h", "fng"]
)


def _f(x) -> Optional[float]:
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


# ======================================================================================
# Parsers puros
# ======================================================================================
def parse_binance_taker_ratio(rows: list, now_ms: int, bars: int = 24) -> Optional[dict]:
    """Velas de 1 h: fracción del volumen que fue compra agresiva (taker buy) en las últimas `bars` velas CERRADAS.
    Fila: [open_time, o, h, l, c, volume, close_time, quote_vol, trades, taker_buy_base, taker_buy_quote, _]."""
    closed = [r for r in rows if int(r[6]) < now_ms]
    if len(closed) < bars:
        return None
    tail = closed[-bars:]
    vol = sum(float(r[5]) for r in tail)
    buy = sum(float(r[9]) for r in tail)
    return {"ratio": buy / vol if vol > 0 else None, "price": float(tail[-1][4])}


def parse_book_imbalance(payload: dict, levels: int = 100) -> Optional[dict]:
    """Desbalance (compradores − vendedores)/(total) en notional de los primeros `levels` niveles de cada lado.
    Cubre una franja de precio MUY angosta (alrededor del cruce): es presión cerca del precio, fácil de manipular; se registra
    junto con la franja cubierta para no sobreinterpretar."""
    bids, asks = payload.get("bids") or [], payload.get("asks") or []
    if not bids or not asks:
        return None
    b = [(float(x[0]), float(x[1])) for x in bids[:levels]]
    a = [(float(x[0]), float(x[1])) for x in asks[:levels]]
    nb, na = sum(p * q for p, q in b), sum(p * q for p, q in a)
    if nb + na <= 0:
        return None
    mid = (b[0][0] + a[0][0]) / 2
    return {"imb": (nb - na) / (nb + na), "cover_pct": (a[-1][0] - b[-1][0]) / mid}


def _okx_data(payload: dict) -> list:
    if str(payload.get("code")) != "0":
        raise ValueError(f"OKX code={payload.get('code')} {payload.get('msg')}")
    return payload.get("data") or []


def parse_okx_funding(payload: dict) -> Optional[float]:
    d = _okx_data(payload)
    return _f(d[0].get("fundingRate")) if d else None


def parse_okx_open_interest_usd(payload: dict, price: Optional[float] = None) -> Optional[float]:
    d = _okx_data(payload)
    if not d:
        return None
    v = _f(d[0].get("oiUsd"))
    if v is not None:
        return v
    ccy = _f(d[0].get("oiCcy"))
    return ccy * price if ccy is not None and price else None


def parse_okx_latest_pair(payload: dict, col: int = 1) -> Optional[float]:
    """Series de rubik: data = [[ts, v1, v2…], …] con la más reciente primero."""
    d = _okx_data(payload)
    return _f(d[0][col]) if d and len(d[0]) > col else None


def parse_okx_taker_buy_ratio(payload: dict) -> Optional[float]:
    """rubik/taker-volume: [ts, sellVol, buyVol]. Devuelve buy/(buy+sell) del último periodo."""
    d = _okx_data(payload)
    if not d or len(d[0]) < 3:
        return None
    sell, buy = _f(d[0][1]), _f(d[0][2])
    return buy / (buy + sell) if sell is not None and buy is not None and buy + sell > 0 else None


def parse_okx_liquidations(payload: dict, ct_val: float) -> dict:
    """Liquidaciones recientes que OKX devuelve (una ventana de las últimas horas, no un día completo). USD = contratos × ctVal × precio."""
    long_usd = short_usd = 0.0
    n = 0
    first = last = None
    for blk in _okx_data(payload):
        for x in blk.get("details", []):
            sz, px = _f(x.get("sz")), _f(x.get("bkPx"))
            if sz is None or px is None:
                continue
            usd = sz * ct_val * px
            is_long = x.get("posSide") == "long" or (x.get("posSide") in (None, "", "net") and x.get("side") == "sell")
            long_usd += usd if is_long else 0.0
            short_usd += 0.0 if is_long else usd
            n += 1
            ts = _f(x.get("ts"))
            if ts is not None:
                first = ts if first is None else min(first, ts)
                last = ts if last is None else max(last, ts)
    return {"long_usd": long_usd, "short_usd": short_usd, "n": n, "from_ms": first, "to_ms": last}


def parse_kucoin_contracts(payload: dict) -> dict[str, dict]:
    """contracts/active → {BASE: {funding, oi_usd, mark, turnover24h}} para perpetuos USDT (XBT → BTC)."""
    out = {}
    for c in payload.get("data") or []:
        sym = c.get("symbol", "")
        if not sym.endswith("USDTM") or c.get("status") not in (None, "Open"):
            continue
        base = sym[: -len("USDTM")]
        base = "BTC" if base == "XBT" else base
        mark, oi, mult = _f(c.get("markPrice")), _f(c.get("openInterest")), _f(c.get("multiplier"))
        out[base] = {"funding": _f(c.get("fundingFeeRate")),
                     "oi_usd": oi * abs(mult) * mark if None not in (oi, mult, mark) else None,
                     "mark": mark, "turnover24h": _f(c.get("turnoverOf24h"))}
    return out


def parse_deribit_dvol(payload: dict) -> Optional[float]:
    rows = (payload.get("result") or {}).get("data") or []
    return _f(rows[-1][4]) if rows and len(rows[-1]) >= 5 else None


def parse_coinbase_price(payload: dict) -> Optional[float]:
    return _f(payload.get("price"))


def parse_llama_stable_total(rows: list) -> Optional[dict]:
    """stablecoincharts/all → total circulante en USD y su cambio de 7 días (una fila por día)."""
    pts = []
    for r in rows or []:
        v = _f(((r.get("totalCirculatingUSD") or r.get("totalCirculating") or {}).get("peggedUSD")))
        t = _f(r.get("date"))
        if v is not None and t is not None:
            pts.append((t, v))
    if len(pts) < 8:
        return None
    pts.sort()
    last, prev = pts[-1][1], pts[-8][1]
    return {"total": last, "chg_7d": last / prev - 1 if prev else None, "date": pts[-1][0]}


def parse_gecko_global(payload: dict) -> Optional[dict]:
    d = payload.get("data") or {}
    return {"btc_dominance": _f((d.get("market_cap_percentage") or {}).get("btc")),
            "total_mcap_usd": _f((d.get("total_market_cap") or {}).get("usd")),
            "mcap_chg_24h": _f(d.get("market_cap_change_percentage_24h_usd"))} if d else None


# ======================================================================================
# Recolección (una foto)
# ======================================================================================
def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(UA)
    return s


def collect_flows(session: Optional[requests.Session] = None, now_ms: Optional[int] = None,
                  get: Optional[Callable] = None, fng_fn: Optional[Callable] = None) -> tuple[dict, dict, dict]:
    """Devuelve (fila, estado_por_fuente, kucoin_universo). `get(url, params)` y `fng_fn()` son inyectables para pruebas."""
    s = session or make_session()
    now_ms = now_ms or int(time.time() * 1000)
    get = get or (lambda url, params=None: _http_json(s, url, params, retries=2, timeout=20))
    row: dict = {c: None for c in FLOW_COLUMNS}
    row["ts"] = (now_ms // 3_600_000) * 3_600_000
    status: dict[str, str] = {}

    def step(name, fn):
        try:
            fn()
            status[name] = "ok"
        except Exception as e:                      # una fuente caída no rompe la foto
            status[name] = f"{type(e).__name__}: {e}"[:160]

    prices: dict[str, float] = {}
    kc_all: dict[str, dict] = {}
    for a in ASSETS:
        k = a.lower()

        def binance_taker(a=a, k=k):
            r = parse_binance_taker_ratio(get(f"{BINANCE}/api/v3/klines", {"symbol": f"{a}USDT", "interval": "1h", "limit": 30}), now_ms)
            if r:
                row[f"{k}_taker_buy_ratio_24h"], row[f"{k}_price"] = r["ratio"], r["price"]
                prices[a] = r["price"]

        def binance_book(a=a, k=k):
            r = parse_book_imbalance(get(f"{BINANCE}/api/v3/depth", {"symbol": f"{a}USDT", "limit": 100}))
            if r:
                row[f"{k}_book_imb_top100"] = r["imb"]

        def okx_funding(a=a, k=k):
            row[f"{k}_okx_funding"] = parse_okx_funding(get(f"{OKX}/api/v5/public/funding-rate-history", {"instId": f"{a}-USDT-SWAP", "limit": 1}))

        def okx_oi(a=a, k=k):
            row[f"{k}_okx_oi_usd"] = parse_okx_open_interest_usd(
                get(f"{OKX}/api/v5/public/open-interest", {"instType": "SWAP", "instId": f"{a}-USDT-SWAP"}), prices.get(a))

        def okx_ls(a=a, k=k):
            row[f"{k}_okx_ls_ratio"] = parse_okx_latest_pair(
                get(f"{OKX}/api/v5/rubik/stat/contracts/long-short-account-ratio", {"ccy": a, "period": "1H"}), 1)

        def okx_taker(a=a, k=k):
            row[f"{k}_okx_taker_buy_ratio_1h"] = parse_okx_taker_buy_ratio(
                get(f"{OKX}/api/v5/rubik/stat/taker-volume", {"ccy": a, "instType": "CONTRACTS", "period": "1H"}))

        def okx_liq(a=a, k=k):
            ct = OKX_CTVAL_FALLBACK[a]
            try:
                d = _okx_data(get(f"{OKX}/api/v5/public/instruments", {"instType": "SWAP", "instId": f"{a}-USDT-SWAP"}))
                ct = _f(d[0].get("ctVal")) or ct
            except Exception:
                pass
            r = parse_okx_liquidations(get(f"{OKX}/api/v5/public/liquidation-orders",
                                           {"instType": "SWAP", "uly": f"{a}-USDT", "state": "filled"}), ct)
            row[f"{k}_liq_long_usd"], row[f"{k}_liq_short_usd"], row[f"{k}_liq_n"] = r["long_usd"], r["short_usd"], r["n"]

        def dvol(a=a, k=k):
            row[f"{k}_dvol"] = parse_deribit_dvol(get(f"{DERIBIT}/api/v2/public/get_volatility_index_data",
                                                      {"currency": a, "start_timestamp": now_ms - 6 * 3_600_000, "end_timestamp": now_ms,
                                                       "resolution": 3600}))

        def cb(a=a, k=k):
            px = parse_coinbase_price(get(f"{COINBASE}/products/{a}-USD/ticker"))
            if px and prices.get(a):
                row[f"{k}_coinbase_premium"] = px / prices[a] - 1.0    # USD vs USDT: incluye la base USDT/USD, no es solo "demanda de EE. UU."

        step(f"binance_taker_{a}", binance_taker)
        step(f"binance_book_{a}", binance_book)
        step(f"okx_funding_{a}", okx_funding)
        step(f"okx_oi_{a}", okx_oi)
        step(f"okx_ls_{a}", okx_ls)
        step(f"okx_taker_{a}", okx_taker)
        step(f"okx_liq_{a}", okx_liq)
        step(f"deribit_dvol_{a}", dvol)
        step(f"coinbase_{a}", cb)

    def kucoin():
        kc_all.update(parse_kucoin_contracts(get(f"{KUCOIN_FUT}/api/v1/contracts/active")))
        for a in ASSETS:
            if a in kc_all:
                row[f"{a.lower()}_kc_funding"], row[f"{a.lower()}_kc_oi_usd"] = kc_all[a]["funding"], kc_all[a]["oi_usd"]

    def llama():
        r = parse_llama_stable_total(get(f"{LLAMA}/stablecoincharts/all"))
        if r:
            row["stable_total_usd"], row["stable_chg_7d"] = r["total"], r["chg_7d"]

    def gecko():
        r = parse_gecko_global(get(f"{GECKO}/api/v3/global"))
        if r:
            row.update(btc_dominance=r["btc_dominance"], total_mcap_usd=r["total_mcap_usd"], mcap_chg_24h=r["mcap_chg_24h"])

    def fng():
        r = (fng_fn or (lambda: fetch_fear_greed(s)))()
        row["fng"] = r["value"] if r else None
        if not r:
            raise RuntimeError("sin respuesta")

    step("kucoin_contracts", kucoin)
    step("defillama_stablecoins", llama)
    step("coingecko_global", gecko)
    step("fear_greed", fng)
    return row, status, kc_all
