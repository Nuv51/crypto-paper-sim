"""Backtest "en frío": reproduce un periodo pasado con el MISMO motor, los MISMOS bots y la MISMA configuración del simulador en vivo.

Qué hace distinto del forward test (y nada más):
  * Los datos vienen de un rango de fechas fijo (velas cerradas de Binance, y del perpetuo/funding de KuCoin para el carry).
  * Se descargan velas ANTERIORES al inicio solo para calentar los indicadores (es información que existía en ese momento);
    el primer bar simulado es exactamente el de `start_ms`.
  * El bot de arbitraje XRP no tiene historial de libros de órdenes: sin foto, no mide nada (se queda sin operar y se avisa).

Qué NO hace: no ajusta parámetros, no elige monedas mirando el resultado, no corrige nada después de ver el desenlace.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from . import metrics
from .cloud import BENCH_SYMBOLS, MARKET_BASKET, benchmarks_from_feed, config_signature
from .data import (COLS, INTERVAL_MS, KUCOIN_FUT, KUCOIN_GRANULARITY, MarketFeed, _empty, _http_json, kucoin_contract,
                   parse_kucoin_funding, parse_kucoin_futures_klines, rail_snapshot_columns)
from .engine import Engine
from .export import build_dashboard
from .ledger import Ledger

DAY_MS = 86_400_000


def ms(date: str) -> int:
    return int(pd.Timestamp(date, tz="UTC").timestamp() * 1000)


class HistoricFeed(MarketFeed):
    """Velas CERRADAS de un rango [start_ms, end_ms) (end_ms exclusivo)."""

    def closed_range(self, symbol: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        step = INTERVAL_MS[interval]
        if symbol.endswith("~PERP"):
            return self._perp_range(symbol, interval, start_ms, end_ms)
        if symbol.endswith("~RAIL"):
            df = self.closed_range("XRPUSDT", interval, start_ms, end_ms).copy()
            for c in rail_snapshot_columns():
                df[c] = np.nan                                   # sin historial del libro: el bot no mide nada
            return df
        df = self.fetch_klines(symbol, interval, start_ms=start_ms, end_ms=end_ms - 1)
        if df.empty:
            raise RuntimeError(f"Binance no devolvió velas de {symbol} entre {start_ms} y {end_ms}")
        df = df[(df.index >= start_ms) & (df.index + step <= end_ms)][COLS]
        return df[~df.index.duplicated(keep="last")].sort_index()

    def _perp_range(self, symbol: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        if interval not in KUCOIN_GRANULARITY:
            raise ValueError(f"El perpetuo de KuCoin no está implementado para velas de {interval}")
        step, contract = INTERVAL_MS[interval], kucoin_contract(symbol)
        frames, cursor = [], start_ms
        while cursor < end_ms:
            end = min(cursor + 190 * step, end_ms)
            payload = _http_json(self.session, KUCOIN_FUT + "/api/v1/kline/query",
                                 {"symbol": contract, "granularity": KUCOIN_GRANULARITY[interval], "from": cursor, "to": end},
                                 timeout=self.timeout)
            frames.append(parse_kucoin_futures_klines(payload))
            cursor = end + step
            time.sleep(self.pause)
        df = pd.concat(frames) if frames else _empty()
        df = df[~df.index.duplicated(keep="last")].sort_index()
        df = df[(df.index >= start_ms) & (df.index + step <= end_ms)]
        if df.empty:
            raise RuntimeError(f"KuCoin no devolvió velas de {contract} en el rango")
        fund: dict[int, float] = {}
        cur = start_ms
        while cur < end_ms:
            end = min(cur + 30 * DAY_MS, end_ms)
            fund.update(parse_kucoin_funding(_http_json(self.session, KUCOIN_FUT + "/api/v1/contract/funding-rates",
                                                        {"symbol": contract, "from": cur, "to": end}, timeout=self.timeout)))
            cur = end + 1
        if not fund:
            raise RuntimeError(f"KuCoin no devolvió funding de {contract} en el rango")
        df = df.copy()
        df["funding"] = [fund.get(int(t), np.nan) for t in df.index]
        return df


UM_MONTHLY = "https://data.binance.vision/data/futures/um/monthly"


def _months(start_ms: int, end_ms: int) -> list[str]:
    a, b = pd.Timestamp(start_ms, unit="ms", tz="UTC"), pd.Timestamp(end_ms - 1, unit="ms", tz="UTC")
    return [f"{p.year:04d}-{p.month:02d}" for p in pd.period_range(a.strftime("%Y-%m"), b.strftime("%Y-%m"), freq="M")]


def parse_um_klines(raw: bytes) -> pd.DataFrame:
    """CSV (con o sin encabezado) del archivo mensual de futuros USD-M de Binance: open_time, open, high, low, close, volume, ..."""
    import io
    df = pd.read_csv(io.BytesIO(raw), header=None)
    if not str(df.iloc[0, 0]).lstrip("-").isdigit():
        df = df.iloc[1:]
    df = df.iloc[:, :6].copy()
    df.columns = ["ts", "open", "high", "low", "close", "volume"]
    df["ts"] = df["ts"].astype("int64")
    df[COLS] = df[COLS].astype(float)
    return df.set_index("ts")[COLS]


def parse_um_funding(raw: bytes) -> dict[int, float]:
    """CSV del archivo mensual de funding: calc_time(ms), [funding_interval_hours], last_funding_rate -> {ms de la hora: tasa por periodo}."""
    import io
    df = pd.read_csv(io.BytesIO(raw), header=None)
    if not str(df.iloc[0, 0]).lstrip("-").isdigit():
        df = df.iloc[1:]
    out: dict[int, float] = {}
    for t, r in zip(df.iloc[:, 0].astype("int64"), df.iloc[:, -1].astype(float)):
        out[int(t) // 3_600_000 * 3_600_000] = float(r)
    return out


class ArchiveHistoricFeed(HistoricFeed):
    """Igual que HistoricFeed, pero el perpetuo y el funding salen del archivo público de futuros USD-M de Binance
    (data.binance.vision), porque KuCoin no entrega historial antiguo. Solo velas de 1 h. Si faltan barras al INICIO del rango
    pedido (el archivo empieza en enero de 2020), se rellenan con el precio spot y funding vacío, hasta 40 días (solo es
    calentamiento: el carry no opera sin 3 observaciones de funding). Si falta más, falla en voz alta."""

    def _get_zip(self, url: str, name: str):
        import io, zipfile
        cache = Path(self.cache_dir) / "um"
        cache.mkdir(parents=True, exist_ok=True)
        f = cache / name
        if not f.exists():
            r = self.session.get(url, timeout=self.timeout)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            f.write_bytes(r.content)
        with zipfile.ZipFile(io.BytesIO(f.read_bytes())) as z:
            return z.read(z.namelist()[0])

    def _perp_range(self, symbol: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        if interval != "1h":
            raise ValueError("El perpetuo del archivo de Binance está implementado solo para velas de 1 h")
        step, base = INTERVAL_MS[interval], symbol[: -len("~PERP")]
        kl, fund = [], {}
        for ym in _months(start_ms, end_ms):
            raw = self._get_zip(f"{UM_MONTHLY}/klines/{base}/1h/{base}-1h-{ym}.zip", f"{base}-1h-{ym}.zip")
            if raw is not None:
                kl.append(parse_um_klines(raw))
            raw = self._get_zip(f"{UM_MONTHLY}/fundingRate/{base}/{base}-fundingRate-{ym}.zip", f"{base}-fundingRate-{ym}.zip")
            if raw is not None:
                fund.update(parse_um_funding(raw))
            time.sleep(self.pause)
        if not kl:
            raise RuntimeError(f"El archivo de Binance no tiene velas del perpetuo {base} en el rango")
        df = pd.concat(kl)
        df = df[~df.index.duplicated(keep="last")].sort_index()
        df = df[(df.index >= start_ms) & (df.index + step <= end_ms)].copy()
        first = int(df.index[0])
        if first > start_ms:
            gap = first - start_ms
            if gap > 40 * 86_400_000:
                raise RuntimeError(f"El perpetuo {base} empieza el {pd.Timestamp(first, unit='ms', tz='UTC'):%Y-%m-%d}: faltan {gap // 86_400_000} días al inicio")
            spot = self.closed_range(base, interval, start_ms, first)
            spot = spot[spot.index < first][COLS]
            df = pd.concat([spot, df])
        df["funding"] = [fund.get(int(t), np.nan) for t in df.index]
        return df


class RangeView:
    """Presenta un rango ya descargado con la misma interfaz que usa `benchmarks_from_feed` (últimas n velas cerradas)."""
    pause = 0

    def __init__(self, feed: HistoricFeed, end_ms: int):
        self.feed, self.end_ms, self._cache = feed, end_ms, {}

    def latest_closed(self, symbol: str, interval: str = "1h", n: int = 600) -> pd.DataFrame:
        key = (symbol, interval, n)
        if key not in self._cache:
            step = INTERVAL_MS[interval]
            self._cache[key] = self.feed.closed_range(symbol, interval, self.end_ms - n * step, self.end_ms)
        return self._cache[key]


def load_frames(feed: HistoricFeed, symbols: list[str], interval: str, start_ms: int, end_ms: int, warm_bars: int,
                log=print) -> dict[str, pd.DataFrame]:
    s0 = start_ms - warm_bars * INTERVAL_MS[interval]
    frames = {}
    for s in symbols:
        frames[s] = feed.closed_range(s, interval, s0, end_ms)
        log(f"  {s}: {len(frames[s])} velas ({pd.Timestamp(int(frames[s].index[0]), unit='ms', tz='UTC'):%Y-%m-%d} → "
            f"{pd.Timestamp(int(frames[s].index[-1]), unit='ms', tz='UTC'):%Y-%m-%d})")
        time.sleep(feed.pause)
    return frames


def _clean(x):
    if isinstance(x, float) and not math.isfinite(x):
        return None
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_clean(v) for v in x]
    return x


def run_backtest(cfg, sim: dict, out_dir: str, start: str = "2025-01-01", end: str = "2026-01-01", feed: Optional[HistoricFeed] = None,
                 frames: Optional[dict] = None, log=print, export_dir: Optional[str] = None) -> dict:
    """Corre el backtest de una configuración (módulo con BOTS, INTERVAL, PORTFOLIO_CAPITAL, PORTFOLIO_RISK) y escribe
    out_dir/dashboard.json y out_dir/summary.json. `frames` permite inyectar datos (pruebas)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    start_ms, end_ms = ms(start), ms(end)
    db = out / "work.db"
    for ext in ("", "-wal", "-shm"):
        Path(str(db) + ext).unlink(missing_ok=True)
    ledger = Ledger(db)
    try:
        eng = Engine(ledger, cfg.BOTS, cfg.PORTFOLIO_CAPITAL, cfg.INTERVAL, portfolio_risk=cfg.PORTFOLIO_RISK)
        feed = feed or HistoricFeed(cache_dir=out / "cache")
        warm = eng.max_warmup + 1
        log(f"{sim['name']}: {len(eng.symbols)} símbolos, velas de {cfg.INTERVAL}, calentamiento {warm} velas, {start} → {end}")
        if frames is None:
            frames = load_frames(feed, eng.symbols + list(getattr(eng, "extra_symbols", [])), cfg.INTERVAL, start_ms, end_ms, warm, log)
        label = f"Binance · velas históricas {start} → {end} (backtest en frío)"
        ledger.set_meta("source", label)
        ledger.set_meta("mode", "backtest")
        ledger.set_meta("interval", cfg.INTERVAL)
        ledger.set_meta("portfolio_capital", cfg.PORTFOLIO_CAPITAL)
        ledger.set_meta("config_sig", config_signature(cfg.BOTS, cfg.PORTFOLIO_CAPITAL, cfg.PORTFOLIO_RISK))
        ledger.set_meta("sim", json.dumps(sim, ensure_ascii=False))
        info = eng.replay(frames, progress=lambda m: log(m))
        if info["first_ts"] != start_ms:
            raise RuntimeError(f"El backtest no empezó en {start}: primera vela simulada {info['first_ts']} (faltan datos de alguna moneda al inicio)")
        if info["last_ts"] != end_ms - INTERVAL_MS[cfg.INTERVAL]:
            raise RuntimeError(f"El backtest no llegó al final del periodo: última vela {info['last_ts']}")
        data = metrics.load_all(ledger.con)
        bench = benchmarks_from_feed(RangeView(feed, end_ms)) if feed is not None and hasattr(feed, "closed_range") else None
        dash = build_dashboard(data, int(time.time() * 1000), benchmarks=bench, fear_greed=None)
        dash["backtest"] = {"start": start, "end": end, "interval": cfg.INTERVAL,
                            "notes": sim.get("notes", [])}
        (out / "dashboard.json").write_text(json.dumps(_clean(dash), separators=(",", ":"), allow_nan=False, ensure_ascii=False), encoding="utf-8")
        bench_roi = buy_and_hold(feed, start_ms, end_ms, log) if hasattr(feed, "closed_range") else {}
        summary = summarize(dash, data, info, sim, bench_roi)
        (out / "summary.json").write_text(json.dumps(_clean(summary), indent=1, ensure_ascii=False), encoding="utf-8")
        if export_dir:                                  # solo lectura, después del resultado: no altera nada de la corrida
            export_tables(ledger.con, Path(export_dir))
        return summary
    finally:
        ledger.close()
        for ext in ("", "-wal", "-shm"):
            Path(str(db) + ext).unlink(missing_ok=True)


def export_tables(con, out: Path) -> None:
    """Vuelca las tablas completas del libro (alta resolución) para el análisis posterior."""
    import pandas as pd
    out.mkdir(parents=True, exist_ok=True)
    for t in ("bots", "trades", "equity", "attrib", "events", "bars", "meta"):
        pd.read_sql_query(f"SELECT * FROM {t}", con).to_csv(out / f"{t}.csv.gz", index=False, compression="gzip")


def buy_and_hold(feed, start_ms: int, end_ms: int, log=print) -> dict:
    """Rendimiento % de comprar y mantener en el MISMO periodo: de la apertura de la primera vela simulada al cierre de la última."""
    out, hourly = {}, {}
    for sym in MARKET_BASKET:
        try:
            df = feed.closed_range(sym, "1h", start_ms, end_ms)
        except Exception as e:                                  # una referencia que falla no debe tumbar el backtest
            log(f"  referencia {sym} no disponible: {e}")
            continue
        hourly[sym] = df
        out[sym] = (float(df["close"].iloc[-1]) / float(df["open"].iloc[0]) - 1) * 100
        time.sleep(getattr(feed, "pause", 0))
    if len(hourly) == len(MARKET_BASKET):
        first = sum(float(hourly[s]["open"].iloc[0]) * q for s, q in MARKET_BASKET.items())
        last = sum(float(hourly[s]["close"].iloc[-1]) * q for s, q in MARKET_BASKET.items())
        out["MARKET"] = (last / first - 1) * 100
    return out


def summarize(dash: dict, data: dict, info: dict, sim: dict, bench_roi: dict | None = None) -> dict:
    """Cifras fijadas de antemano (BACKTEST_2025.md): ROI, caída máxima, Sharpe, comisiones y operaciones, frente a BTC y el mercado."""
    eq = metrics.equity_wide(data["equity"])
    total = eq.sum(axis=1)
    step_h = float(total.index[1] - total.index[0]) / 3_600_000 if len(total) > 1 else 1.0
    r = total.pct_change().dropna()
    sharpe = float(r.mean() / r.std() * math.sqrt(8760 / step_h)) if len(r) > 2 and r.std() > 0 else None
    k = dash["kpis"]
    br = bench_roi or {}
    bots = [{"id": b["id"], "name": b["name"], "strategy": b["strategy"], "capital": b["capital"], "equity": b["equity"],
             "roi": b["roi"], "max_dd": b["max_dd"], "sharpe": b["sharpe"], "n_trades": b["n_trades"], "fees": b["fees"],
             "status": b["status"], "status_reason": b["status_reason"]} for b in dash["bots"]]
    return {"sim": sim.get("id"), "name": sim.get("name"), "capital": k["capital"], "equity": k["equity"], "pnl": k["pnl"],
            "roi": k["roi"], "max_dd": k["max_dd"], "sharpe": sharpe, "fees": k["fees"], "n_trades": k["n_trades"],
            "btc_roi": br.get("BTCUSDT"), "eth_roi": br.get("ETHUSDT"), "market_roi": br.get("MARKET"),
            "first_ts": k["first_ts"], "last_ts": k["last_ts"], "bars": info["bars"], "bots": bots}
