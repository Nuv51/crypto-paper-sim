"""Fuentes de datos: velas reales de Binance (API pública, sin llaves), funding y velas del perpetuo de KuCoin,
fotos del libro de Bitso/Binance/KuCoin para el bot de arbitraje, feed sintético para pruebas y cotizaciones
de CoinMarketCap como verificación cruzada.

Símbolos especiales (los resuelve MarketFeed):
  BTCUSDT~PERP  velas del perpetuo de KuCoin (XBTUSDTM) + columna `funding` en las barras de liquidación (cada 8 h)
  XRP~RAIL      velas de XRPUSDT + (solo en la última barra) la foto del mercado de Bitso, Binance y KuCoin

POR QUÉ BINANCE PÚBLICO COMO FUENTE PRINCIPAL
  CoinMarketCap entrega cotizaciones puntuales; el historial OHLCV está en planes de pago. Para
  simular estrategias sobre velas necesitamos OHLCV, así que las velas vienen de los endpoints
  públicos de Binance (no requieren API key ni firma) y CMC se usa como verificación cruzada del precio.

LÍMITES DE RATE (verifica la documentación vigente de cada servicio)
  * Binance: límite por peso de petición por IP; las respuestas traen X-MBX-USED-WEIGHT-1M. Ante HTTP
    429 hay que esperar (Retry-After); ante 418 te banearon la IP temporalmente. Aquí se pagina con una
    pausa corta entre llamadas y se respeta Retry-After.
  * CoinMarketCap: plan gratuito con tope de llamadas por minuto y créditos mensuales limitados.

Nada de esto usa dinero real ni envía órdenes: solo lee precios.
"""
from __future__ import annotations

import os
import time
import zlib
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import requests

INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
               "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
COLS = ["open", "high", "low", "close", "volume"]


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=COLS, index=pd.Index([], dtype="int64", name="ts"))


# ======================================================================================
# Binance (datos públicos de mercado)
# ======================================================================================
class BinanceFeed:
    name = "binance"
    label = "Binance (mercado real, API pública)"
    # data-api.binance.vision sirve solo datos de mercado; api.binance.com es el respaldo.
    BASES = ("https://data-api.binance.vision", "https://api.binance.com")

    def __init__(self, cache_dir: str | Path = "data/cache", pause: float = 0.2,
                 timeout: float = 15.0):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.pause = pause
        self.timeout = timeout
        self.session = requests.Session()

    # ----------------------------------------------------------------------------- HTTP
    def _get(self, path: str, params: dict, retries: int = 4):
        last_err: Optional[Exception] = None
        for base in self.BASES:
            for attempt in range(retries):
                try:
                    r = self.session.get(base + path, params=params, timeout=self.timeout)
                    if r.status_code in (429, 418):
                        wait = float(r.headers.get("Retry-After", 2 ** attempt))
                        time.sleep(min(wait, 60))
                        continue
                    r.raise_for_status()
                    return r.json()
                except requests.RequestException as e:   # red caída, 5xx, bloqueo regional (451)...
                    last_err = e
                    time.sleep(0.5 * (attempt + 1))
            # pasa al siguiente host base
        raise RuntimeError(f"No pude leer {path} de Binance: {last_err}")

    @staticmethod
    def _to_frame(rows: list) -> pd.DataFrame:
        if not rows:
            return _empty()
        df = pd.DataFrame(rows).iloc[:, :7]
        df.columns = ["ts", "open", "high", "low", "close", "volume", "close_time"]
        df[COLS] = df[COLS].astype(float)
        df["ts"] = df["ts"].astype("int64")
        return df.set_index("ts")[COLS + ["close_time"]]

    def fetch_klines(self, symbol: str, interval: str, start_ms: Optional[int] = None,
                     end_ms: Optional[int] = None) -> pd.DataFrame:
        """Descarga velas paginando de 1000 en 1000. Incluye la vela en formación (se filtra aparte)."""
        step = INTERVAL_MS[interval]
        frames, cursor = [], start_ms
        while True:
            params = {"symbol": symbol, "interval": interval, "limit": 1000}
            if cursor is not None:
                params["startTime"] = int(cursor)
            if end_ms is not None:
                params["endTime"] = int(end_ms)
            rows = self._get("/api/v3/klines", params)
            df = self._to_frame(rows)
            if df.empty:
                break
            frames.append(df)
            last = int(df.index[-1])
            if len(df) < 1000 or (end_ms is not None and last >= end_ms):
                break
            cursor = last + step
            time.sleep(self.pause)
        if not frames:
            return _empty().assign(close_time=pd.Series(dtype="int64"))
        out = pd.concat(frames)
        return out[~out.index.duplicated(keep="last")].sort_index()

    # ----------------------------------------------------------------------------- API
    def history(self, symbol: str, interval: str = "1h", days: int = 120) -> pd.DataFrame:
        """Historial de velas CERRADAS de los últimos `days` días, con caché en CSV."""
        step = INTERVAL_MS[interval]
        now_ms = int(time.time() * 1000)
        need_start = now_ms - days * 86_400_000
        path = self.cache_dir / f"{symbol}_{interval}.csv"
        cached = _empty()
        if path.exists():
            cached = pd.read_csv(path, index_col="ts")
            cached.index = cached.index.astype("int64")
        if cached.empty or int(cached.index[0]) > need_start + step:
            start = need_start                          # el caché no cubre el inicio: descargar todo
            cached = _empty()
        else:
            start = int(cached.index[-1]) + step        # solo lo nuevo
        fresh = self.fetch_klines(symbol, interval, start_ms=start)
        if not fresh.empty:
            fresh = fresh[fresh["close_time"] < now_ms][COLS]     # descarta la vela en formación
        df = pd.concat([cached[COLS], fresh]) if not fresh.empty else cached[COLS]
        df = df[~df.index.duplicated(keep="last")].sort_index()
        df.to_csv(path, index_label="ts")
        return df[df.index >= need_start]

    def latest_closed(self, symbol: str, interval: str = "1h", n: int = 600) -> pd.DataFrame:
        """Las últimas `n` velas cerradas (para el modo live)."""
        rows = self._get("/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": min(n + 1, 1000)})
        df = self._to_frame(rows)
        now_ms = int(time.time() * 1000)
        return df[df["close_time"] < now_ms][COLS]


# ======================================================================================
# KuCoin futuros (perpetuo + funding), Bitso y KuCoin spot (fotos del libro) — todo público, sin llaves
# ======================================================================================
HOUR = 3_600_000
KUCOIN_GRANULARITY = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}   # minutos por vela
KUCOIN_FUT = "https://api-futures.kucoin.com"
KUCOIN_SPOT = "https://api.kucoin.com"
BITSO = "https://api.bitso.com"
RAIL_VENUES = ("bitso", "binance", "kucoin")


def kucoin_contract(symbol: str) -> str:
    """'BTCUSDT~PERP' -> 'XBTUSDTM' (KuCoin llama XBT al bitcoin)."""
    base = symbol.split("~")[0]
    base = base[:-4] if base.endswith("USDT") else base
    return f"{'XBT' if base == 'BTC' else base}USDTM"


def _http_json(session: requests.Session, url: str, params: Optional[dict] = None, retries: int = 3,
               timeout: float = 15.0):
    last: Optional[Exception] = None
    for attempt in range(retries):
        try:
            r = session.get(url, params=params, timeout=timeout)
            if r.status_code == 429:
                time.sleep(min(float(r.headers.get("Retry-After", 2 ** attempt)), 30))
                continue
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            last = e
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"No pude leer {url}: {last}")


FNG_URL = "https://api.alternative.me/fng/"
FNG_CLASSES = {"Extreme Fear": "Miedo extremo", "Fear": "Miedo", "Neutral": "Neutral", "Greed": "Codicia",
               "Extreme Greed": "Codicia extrema"}


def parse_fear_greed(payload: dict) -> dict:
    """Índice Crypto Fear & Greed de alternative.me (0 = miedo extremo, 100 = codicia extrema; sentimiento del mercado
    cripto en general, publicado una vez al día). `data` viene del más reciente al más antiguo."""
    rows = payload["data"]
    pick = lambda i: ({"value": int(rows[i]["value"]), "ts": int(rows[i]["timestamp"]) * 1000} if len(rows) > i else None)
    cur = rows[0]
    return {"value": int(cur["value"]), "label": FNG_CLASSES.get(cur.get("value_classification"), cur.get("value_classification")),
            "ts": int(cur["timestamp"]) * 1000, "yesterday": pick(1), "week": pick(7), "month": pick(30),
            "source": "alternative.me"}


def fetch_fear_greed(session: Optional[requests.Session] = None) -> Optional[dict]:
    """Opcional: si la fuente no responde devuelve None (el tablero solo omite el medidor); nunca rompe la corrida."""
    try:
        return parse_fear_greed(_http_json(session or requests.Session(), FNG_URL, {"limit": 31, "format": "json"}, retries=2))
    except Exception:
        return None


def parse_kucoin_futures_klines(payload: dict) -> pd.DataFrame:
    """data: [[ms, open, high, low, close, volume, turnover], ...] (verificado contra la API real el 2026-10-16)."""
    rows = payload.get("data") or []
    if not rows:
        return _empty()
    df = pd.DataFrame(rows).iloc[:, :6]
    df.columns = ["ts", "open", "high", "low", "close", "volume"]
    df["ts"] = df["ts"].astype("int64")
    df[COLS] = df[COLS].astype(float)
    return df.set_index("ts")[COLS]


def parse_kucoin_funding(payload: dict) -> dict[int, float]:
    """data: [{symbol, fundingRate, timepoint(ms)}, ...] -> {ms de la hora de liquidación: tasa por periodo}."""
    out: dict[int, float] = {}
    for r in payload.get("data") or []:
        out[int(r["timepoint"]) // HOUR * HOUR] = float(r["fundingRate"])
    return out


def rail_snapshot_columns() -> list[str]:
    cols = [f"{v}_{c}" for v in RAIL_VENUES for c in ("bid", "ask", "bq", "aq")]
    return cols + ["bitso_mxn_gap"]


class MarketFeed(BinanceFeed):
    """Binance spot (velas) + los símbolos especiales de arriba. Las fuentes auxiliares fallan en voz alta
    (el perpetuo es indispensable para el bot de carry) salvo la foto de Bitso/KuCoin, que es opcional:
    si no responde, esa barra queda sin foto y el bot de arbitraje simplemente no mide nada."""
    name = "market"
    label = "Mercado real (Binance · KuCoin · Bitso, APIs públicas)"

    # ----------------------------------------------------------------------------- perpetuo
    def _perp_frame(self, symbol: str, interval: str, bars: int) -> pd.DataFrame:
        if interval not in KUCOIN_GRANULARITY:
            raise ValueError(f"El perpetuo de KuCoin no está implementado para velas de {interval}")
        step = INTERVAL_MS[interval]
        contract, now_ms = kucoin_contract(symbol), int(time.time() * 1000)
        start = (now_ms // step - bars - 2) * step
        frames, cursor = [], start
        while cursor < now_ms:
            end = min(cursor + 190 * step, now_ms)                  # KuCoin devuelve máx. ~200 velas por petición
            payload = _http_json(self.session, KUCOIN_FUT + "/api/v1/kline/query",
                                 {"symbol": contract, "granularity": KUCOIN_GRANULARITY[interval], "from": cursor, "to": end},
                                 timeout=self.timeout)
            frames.append(parse_kucoin_futures_klines(payload))
            cursor = end + step
            time.sleep(self.pause)
        df = pd.concat(frames) if frames else _empty()
        df = df[~df.index.duplicated(keep="last")].sort_index()
        df = df[df.index + step <= now_ms]                         # solo velas cerradas
        if df.empty:
            raise RuntimeError(f"KuCoin no devolvió velas de {contract}")
        fund: dict[int, float] = {}
        cur = start
        while cur < now_ms:
            end = min(cur + 30 * 86_400_000, now_ms)
            fund.update(parse_kucoin_funding(_http_json(
                self.session, KUCOIN_FUT + "/api/v1/contract/funding-rates",
                {"symbol": contract, "from": cur, "to": end}, timeout=self.timeout)))
            cur = end + 1
        if not fund:
            raise RuntimeError(f"KuCoin no devolvió funding de {contract}")
        df = df.copy()
        df["funding"] = [fund.get(int(t), np.nan) for t in df.index]
        return df

    # ----------------------------------------------------------------------------- foto del mercado XRP
    def rail_snapshot(self) -> dict[str, float]:
        out = {c: float("nan") for c in rail_snapshot_columns()}

        def quote(venue, fn):
            try:
                bid, ask, bq, aq = fn()
                out.update({f"{venue}_bid": bid, f"{venue}_ask": ask, f"{venue}_bq": bq, f"{venue}_aq": aq})
            except Exception:
                pass                                              # foto opcional: esa casa queda sin dato

        def bitso():
            t = _http_json(self.session, BITSO + "/v3/ticker/", {"book": "xrp_usdt"}, 2, self.timeout)["payload"]
            bid, ask, bq, aq = float(t["bid"]), float(t["ask"]), float("nan"), float("nan")
            try:                                                  # tamaños de la punta del libro (opcional)
                ob = _http_json(self.session, BITSO + "/v3/order_book/", {"book": "xrp_usdt", "aggregate": "true"},
                                2, self.timeout)["payload"]
                bq, aq = float(ob["bids"][0]["amount"]), float(ob["asks"][0]["amount"])
            except Exception:
                pass
            return bid, ask, bq, aq

        def binance():
            t = self._get("/api/v3/ticker/bookTicker", {"symbol": "XRPUSDT"})
            return float(t["bidPrice"]), float(t["askPrice"]), float(t["bidQty"]), float(t["askQty"])

        def kucoin():
            d = _http_json(self.session, KUCOIN_SPOT + "/api/v1/market/orderbook/level1", {"symbol": "XRP-USDT"},
                           2, self.timeout)["data"]
            return float(d["bestBid"]), float(d["bestAsk"]), float(d["bestBidSize"]), float(d["bestAskSize"])

        quote("bitso", bitso)
        quote("binance", binance)
        quote("kucoin", kucoin)
        try:                                                      # ruta MXN: xrp_mxn / usdt_mxn frente al precio en USDT
            x = _http_json(self.session, BITSO + "/v3/ticker/", {"book": "xrp_mxn"}, 2, self.timeout)["payload"]
            u = _http_json(self.session, BITSO + "/v3/ticker/", {"book": "usdt_mxn"}, 2, self.timeout)["payload"]
            implied = (float(x["bid"]) + float(x["ask"])) / 2 / ((float(u["bid"]) + float(u["ask"])) / 2)
            ref = (out["binance_bid"] + out["binance_ask"]) / 2
            out["bitso_mxn_gap"] = implied / ref - 1.0
        except Exception:
            pass
        return out

    def _rail_frame(self, base: pd.DataFrame) -> pd.DataFrame:
        df = base.copy()
        for c in rail_snapshot_columns():
            df[c] = np.nan
        snap = self.rail_snapshot()
        for c, v in snap.items():
            df.iloc[-1, df.columns.get_loc(c)] = v
        return df

    # ----------------------------------------------------------------------------- API
    def latest_closed(self, symbol: str, interval: str = "1h", n: int = 600) -> pd.DataFrame:
        if symbol.endswith("~PERP"):
            return self._perp_frame(symbol, interval, n)
        if symbol.endswith("~RAIL"):
            return self._rail_frame(super().latest_closed("XRPUSDT", interval, n))
        return super().latest_closed(symbol, interval, n)

    def history(self, symbol: str, interval: str = "1h", days: int = 120) -> pd.DataFrame:
        if symbol.endswith("~PERP"):
            return self._perp_frame(symbol, interval, days * 86_400_000 // INTERVAL_MS[interval])
        if symbol.endswith("~RAIL"):
            base = super().history("XRPUSDT", interval, days)
            df = base.copy()
            for c in rail_snapshot_columns():
                df[c] = np.nan                                    # no hay foto histórica del libro: el replay no mide nada
            return df
        return super().history(symbol, interval, days)


# ======================================================================================
# Feed sintético (SOLO para probar el código; no representa ningún mercado real)
# ======================================================================================
class SyntheticFeed:
    name = "synthetic"
    label = "SINTÉTICO (datos inventados, solo para pruebas)"
    BASE_PRICE = {"BTCUSDT": 65000.0, "ETHUSDT": 3200.0, "BNBUSDT": 580.0, "ADAUSDT": 0.45,
                  "SOLUSDT": 150.0, "AVAXUSDT": 35.0, "DOGEUSDT": 0.15, "LINKUSDT": 14.0, "XRPUSDT": 1.34,
                  "DOTUSDT": 4.2, "LTCUSDT": 85.0, "ATOMUSDT": 5.0, "XLMUSDT": 0.27, "NEARUSDT": 3.1, "SUIUSDT": 2.6,
                  "APTUSDT": 4.5, "INJUSDT": 14.0, "ARBUSDT": 0.40, "OPUSDT": 0.80}
    BASE_VOL = {"BTCUSDT": 0.0045, "ETHUSDT": 0.0060, "BNBUSDT": 0.0055, "ADAUSDT": 0.0075,
                "SOLUSDT": 0.0095, "AVAXUSDT": 0.0095, "DOGEUSDT": 0.0120, "LINKUSDT": 0.0090, "XRPUSDT": 0.0085,
                "DOTUSDT": 0.0090, "LTCUSDT": 0.0075, "ATOMUSDT": 0.0090, "XLMUSDT": 0.0085, "NEARUSDT": 0.0100,
                "SUIUSDT": 0.0110, "APTUSDT": 0.0105, "INJUSDT": 0.0115, "ARBUSDT": 0.0105, "OPUSDT": 0.0105}
    END_MS = int(pd.Timestamp("2026-10-01", tz="UTC").timestamp() * 1000)

    def __init__(self, seed: int = 7):
        self.seed = seed

    STABLES = ("USDCUSDT", "FDUSDUSDT")

    def history(self, symbol: str, interval: str = "1h", days: int = 120) -> pd.DataFrame:
        if symbol in self.STABLES:
            return self._stable(symbol, interval, days)
        if symbol.endswith("~PERP"):
            return self._perp(symbol, interval, days)
        if symbol.endswith("~RAIL"):
            return self._rail(symbol, interval, days)
        step = INTERVAL_MS[interval]
        n = int(days * 86_400_000 // step)
        rng = np.random.default_rng(zlib.crc32(symbol.encode()) ^ self.seed)
        sig0 = self.BASE_VOL.get(symbol, 0.008) * np.sqrt(step / 3_600_000)

        # regímenes con cambio de estado (rango / alcista / bajista) y volatilidad que se agrupa
        regime = 0
        drift = {0: 0.0, 1: 0.00025, 2: -0.00025}
        vol = sig0
        close = np.empty(n)
        px = self.BASE_PRICE.get(symbol, 10.0)
        anchor = px
        rets = np.empty(n)
        for t in range(n):
            if rng.random() < 0.004:
                regime = int(rng.choice([0, 1, 2], p=[0.5, 0.25, 0.25]))
            vol = 0.97 * vol + 0.03 * sig0 + 0.15 * sig0 * abs(rng.standard_normal()) * 0.3
            r = drift[regime] * (step / 3_600_000) + vol * rng.standard_normal()
            if regime == 0:                       # en rango: reversión suave hacia un ancla
                r += -0.02 * np.log(px / anchor)
            else:
                anchor = 0.995 * anchor + 0.005 * px
            px *= np.exp(r)
            close[t], rets[t] = px, r
        open_ = np.concatenate([[close[0] / np.exp(rets[0])], close[:-1]])
        wick = np.abs(rng.standard_normal(n)) * sig0 * 0.5
        high = np.maximum(open_, close) * np.exp(wick)
        low = np.minimum(open_, close) * np.exp(-np.abs(rng.standard_normal(n)) * sig0 * 0.5)
        volume = np.exp(rng.normal(5, 0.5, n)) * (1 + 40 * np.abs(rets) / sig0)
        idx = (self.END_MS - step * (n - np.arange(n))).astype("int64")
        return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume},
                            index=pd.Index(idx, name="ts"))


    # ---- extensiones sintéticas (solo para pruebas) -------------------------------------------------
    def _index(self, interval: str, days: int):
        step = INTERVAL_MS[interval]
        n = int(days * 86_400_000 // step)
        return n, (self.END_MS - step * (n - np.arange(n))).astype("int64")

    def _stable(self, symbol: str, interval: str, days: int) -> pd.DataFrame:
        n, idx = self._index(interval, days)
        rng = np.random.default_rng(zlib.crc32(symbol.encode()) ^ self.seed)
        x, close = 0.0, np.empty(n)
        for t in range(n):
            x = 0.92 * x + 0.0003 * rng.standard_normal()
            if rng.random() < 0.0025:                         # choque puntual de peg que luego revierte
                x -= rng.uniform(0.003, 0.012)
            close[t] = 1.0 + x
        open_ = np.concatenate([[1.0], close[:-1]])
        wick = np.abs(rng.standard_normal(n)) * 0.0002
        return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) + wick,
                             "low": np.minimum(open_, close) - wick, "close": close,
                             "volume": np.exp(rng.normal(12, 0.4, n))}, index=pd.Index(idx, name="ts"))

    def _perp(self, symbol: str, interval: str, days: int) -> pd.DataFrame:
        spot = self.history(symbol.split("~")[0], interval, days)
        rng = np.random.default_rng(zlib.crc32(symbol.encode()) ^ self.seed)
        n = len(spot)
        basis, level = 0.0003, 0.0001
        b = np.empty(n)
        fund = np.full(n, np.nan)
        for t in range(n):
            basis = 0.9 * basis + 0.1 * 0.0003 + 0.0002 * rng.standard_normal()
            b[t] = basis
            if (int(spot.index[t]) // 3_600_000) % 8 == 0:    # liquidación cada 8 h (00, 08, 16 UTC)
                level = 0.97 * level + 0.03 * 0.0001 + 0.00005 * rng.standard_normal()
                if rng.random() < 0.01:                       # regímenes de funding alto / negativo
                    level += rng.choice([0.0004, -0.0003])
                fund[t] = float(np.clip(level + 0.3 * basis, -0.0005, 0.0010))
        mult = 1.0 + b
        out = spot.copy()
        for c in ("open", "high", "low", "close"):
            out[c] = spot[c].to_numpy() * mult
        out["funding"] = fund
        return out

    RAIL_VENUES = {"bitso": 0.0006, "binance": 0.00005, "kucoin": 0.0002}

    def _rail(self, symbol: str, interval: str, days: int) -> pd.DataFrame:
        base = self.history("XRPUSDT", interval, days)
        rng = np.random.default_rng(zlib.crc32(symbol.encode()) ^ self.seed)
        n, px = len(base), base["close"].to_numpy()
        out = base.copy()
        for v, half in self.RAIL_VENUES.items():
            off = 0.0002 * rng.standard_normal(n)
            if v == "bitso":                                  # Bitso a veces se desalinea (raro): oportunidades escasas
                shock = (rng.random(n) < 0.01) * rng.choice([-1, 1], n) * rng.uniform(0.004, 0.012, n)
                off = off + shock
            mid = px * (1 + off)
            out[f"{v}_bid"], out[f"{v}_ask"] = mid * (1 - half), mid * (1 + half)
            out[f"{v}_bq"], out[f"{v}_aq"] = 20_000.0 + 0 * mid, 20_000.0 + 0 * mid
        out["bitso_mxn_gap"] = 0.0015 * rng.standard_normal(n)
        return out


# ======================================================================================
# CoinMarketCap (verificación cruzada de precio; requiere CMC_API_KEY en el entorno)
# ======================================================================================
class CoinMarketCapQuotes:
    URL = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 15.0):
        self.api_key = api_key or os.environ.get("CMC_API_KEY")
        if not self.api_key:
            raise RuntimeError("Falta la variable de entorno CMC_API_KEY (nunca pongas la llave en el código).")
        self.timeout = timeout

    def latest(self, symbols: list[str], convert: str = "USD") -> dict[str, float]:
        r = requests.get(self.URL, params={"symbol": ",".join(symbols), "convert": convert},
                         headers={"X-CMC_PRO_API_KEY": self.api_key, "Accept": "application/json"},
                         timeout=self.timeout)
        r.raise_for_status()
        data = r.json()["data"]
        out: dict[str, float] = {}
        for sym, entries in data.items():
            entries = entries if isinstance(entries, list) else [entries]
            # un mismo ticker puede repetirse entre proyectos distintos: nos quedamos con el mejor rank
            best = min(entries, key=lambda e: e.get("cmc_rank") or 10 ** 9)
            out[sym] = float(best["quote"][convert]["price"])
        return out
