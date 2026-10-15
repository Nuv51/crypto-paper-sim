"""Fuentes de datos: velas reales de Binance (API pública, sin llaves), feed sintético para pruebas
y cotizaciones de CoinMarketCap como verificación cruzada.

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
# Feed sintético (SOLO para probar el código; no representa ningún mercado real)
# ======================================================================================
class SyntheticFeed:
    name = "synthetic"
    label = "SINTÉTICO (datos inventados, solo para pruebas)"
    BASE_PRICE = {"BTCUSDT": 65000.0, "ETHUSDT": 3200.0, "BNBUSDT": 580.0, "ADAUSDT": 0.45,
                  "SOLUSDT": 150.0, "AVAXUSDT": 35.0, "DOGEUSDT": 0.15, "LINKUSDT": 14.0}
    BASE_VOL = {"BTCUSDT": 0.0045, "ETHUSDT": 0.0060, "BNBUSDT": 0.0055, "ADAUSDT": 0.0075,
                "SOLUSDT": 0.0095, "AVAXUSDT": 0.0095, "DOGEUSDT": 0.0120, "LINKUSDT": 0.0090}
    END_MS = int(pd.Timestamp("2026-10-01", tz="UTC").timestamp() * 1000)

    def __init__(self, seed: int = 7):
        self.seed = seed

    def history(self, symbol: str, interval: str = "1h", days: int = 120) -> pd.DataFrame:
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
