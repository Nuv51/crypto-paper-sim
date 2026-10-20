"""Un paso incremental para correr en la nube.

Cada ejecución programada es una sesión NUEVA, sin disco compartido: el estado completo viaja en un
JSON (snapshot del ledger). La simulación no depende de CUÁNDO corre: cada vela se procesa en orden, así
que correr cada hora, cada 6 horas o una vez al día da el mismo resultado (solo cambia qué tan fresco está el tablero).

Códigos de salida de run_step: 0 ok · 1 error inesperado · 2 sin datos/red (el estado NO se toca).
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Optional

from . import metrics
from .data import MarketFeed, SyntheticFeed, INTERVAL_MS, fetch_fear_greed
from .engine import Engine
from .export import build_dashboard
from .ledger import Ledger

WINDOW = 700


class DataUnavailable(Exception):
    pass


BENCH_SYMBOLS = ("BTCUSDT", "ETHUSDT")

# "El mercado": índice ponderado por capitalización de las 10 mayores monedas no estables que cotizan en Binance.
# Es el valor de una canasta con cantidades fijas (suministro circulante APROXIMADO, en unidades de la moneda), así que
# su rendimiento es el de un índice de capitalización sin rebalanceos. No es el total del mercado cripto (no incluye
# miles de monedas pequeñas); los suministros cambian poco y no se actualizan solos. Es una referencia, no un dato oficial.
MARKET_BASKET = {"BTCUSDT": 20.0e6, "ETHUSDT": 120.7e6, "XRPUSDT": 60.0e9, "BNBUSDT": 140.0e6, "SOLUSDT": 550.0e6,
                 "DOGEUSDT": 151.0e9, "ADAUSDT": 36.0e9, "TRXUSDT": 94.7e9, "AVAXUSDT": 420.0e6, "LINKUSDT": 680.0e6}


def _fetch_hd(feed, sym: str):
    h = feed.latest_closed(sym, "1h", 768)
    time.sleep(getattr(feed, "pause", 0))
    d = feed.latest_closed(sym, "1d", 365)
    time.sleep(getattr(feed, "pause", 0))
    if h.empty or d.empty:
        raise ValueError(f"sin velas de {sym}")
    return h, d


def _with_now(d_ts: list, d_cl: list, h_ts: int, h_cl: float):
    """A la serie diaria se le agrega el último cierre horario para que llegue "hasta ahora"."""
    if h_ts > d_ts[-1]:
        d_ts, d_cl = d_ts + [h_ts], d_cl + [h_cl]
    return d_ts, d_cl


def _market_index(frames: dict) -> Optional[dict]:
    """Índice de la canasta a partir de {símbolo: (velas_h, velas_d)}; solo usa las marcas de tiempo comunes a todas."""
    import pandas as pd
    out = {}
    for key, idx_pos in (("h", 0), ("d", 1)):
        cols = {s: fr[idx_pos]["close"].astype(float) for s, fr in frames.items()}
        df = pd.DataFrame(cols).dropna()
        if len(df) < 2:
            return None
        val = sum(df[s] * MARKET_BASKET[s] for s in df.columns) / 1e9           # miles de millones de USD
        out[key] = (df.index, val)
    hts, hv = out["h"]
    dts, dv = out["d"]
    d_ts, d_cl = _with_now([int(t) for t in dts], [float(v) for v in dv], int(hts[-1]), float(hv.iloc[-1]))
    return {"h": {"ts": [int(t) for t in hts], "close": [round(float(v), 4) for v in hv]},
            "d": {"ts": d_ts, "close": [round(v, 4) for v in d_cl]}}


def benchmarks_from_feed(feed) -> Optional[dict]:
    """Historia de BTC, ETH y del índice de mercado para comparar el portafolio en periodos largos (día, semana, mes,
    3 meses, año).

    Velas horarias de ~32 días y diarias de 365. A la serie diaria se le agrega el último cierre horario para que el
    rendimiento llegue "hasta ahora" y no hasta el cierre de ayer. Es OPCIONAL: si BTC o ETH fallan devuelve None y el
    tablero simplemente no ofrece los periodos largos; si solo falla el índice de mercado, se omite esa línea. Nunca
    hace fallar la corrida.
    """
    if not hasattr(feed, "latest_closed"):
        return None
    out: dict = {}
    frames: dict = {}
    try:
        for sym in BENCH_SYMBOLS:
            h, d = _fetch_hd(feed, sym)
            frames[sym] = (h, d)
            dts = [int(t) for t in d.index]
            dcl = [float(v) for v in d["close"]]
            dts, dcl = _with_now(dts, dcl, int(h.index[-1]), float(h["close"].iloc[-1]))
            out[sym] = {"h": {"ts": [int(t) for t in h.index], "close": [round(float(v), 4) for v in h["close"]]},
                        "d": {"ts": dts, "close": [round(v, 4) for v in dcl]}}
    except Exception:
        return None
    try:                                                       # el índice de mercado es un extra: si falla, se omite
        for sym in MARKET_BASKET:
            if sym not in frames:
                frames[sym] = _fetch_hd(feed, sym)
        mk = _market_index(frames)
        if mk:
            out["MARKET"] = mk
    except Exception:
        pass
    return out


def config_signature(bots_cfg: list[dict], capital: float, portfolio_risk: Optional[dict] = None) -> str:
    """Huella de la configuración. Si cambia a mitad de una simulación, no se mezclan resultados de reglas distintas."""
    body = {"capital": capital, "bots": bots_cfg}
    if portfolio_risk:                     # el freno global también es una regla: cambiarlo reinicia la prueba
        body["portfolio_risk"] = portfolio_risk
    blob = json.dumps(body, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _write(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, separators=(",", ":"), allow_nan=False, ensure_ascii=False), encoding="utf-8")


def _frames(feed, source: str, symbols: list[str], interval: str, ledger: Ledger, advance: int):
    bar_ms = INTERVAL_MS[interval]
    if source == "synthetic":                      # SOLO para pruebas: revela `advance` velas nuevas por corrida
        full = {s: feed.history(s, interval, 60) for s in symbols}
        common = sorted(set.intersection(*[set(int(t) for t in f.index) for f in full.values()]))
        last_ts = int(ledger.get_meta("last_ts", 0) or 0)
        until = common[800] if not last_ts else min(last_ts + advance * bar_ms, common[-1])
        return {s: f[f.index <= until].tail(WINDOW) for s, f in full.items()}
    try:
        frames = {}
        for s in symbols:
            frames[s] = feed.latest_closed(s, interval, WINDOW)
            time.sleep(getattr(feed, "pause", 0))
        return frames
    except Exception as e:
        raise DataUnavailable(f"No pude leer datos de mercado: {type(e).__name__}: {e}") from e


def run_step(bots_cfg: list[dict], interval: str, capital: float, state_path: Optional[str], out_dir: str,
             source: str = "binance", feed=None, synthetic_advance: int = 24, seed: int = 7,
             portfolio_risk: Optional[dict] = None, sim: Optional[dict] = None) -> tuple[int, dict]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    now_ms = int(time.time() * 1000)
    status = {"ts": now_ms, "ok": False, "source": source, "message": "", "bars_processed": 0, "resumed": False}
    db = out / "work.db"
    for ext in ("", "-wal", "-shm"):
        Path(str(db) + ext).unlink(missing_ok=True)
    ledger, code = None, 1
    try:
        feed = feed or (SyntheticFeed(seed=seed) if source == "synthetic" else MarketFeed(cache_dir=out / "cache"))
        label = feed.label
        ledger = Ledger(db)
        sp = Path(state_path) if state_path else None
        resumed = bool(sp and sp.exists())
        if resumed:
            ledger.restore(json.loads(sp.read_text(encoding="utf-8")))
            prev = ledger.get_meta("source")
            if prev and prev != label:
                raise ValueError(f"El estado guardado viene de '{prev}' y esta corrida usa '{label}': no se mezclan fuentes")
        sig = config_signature(bots_cfg, capital, portfolio_risk)
        if resumed:
            prev_sig = ledger.get_meta("config_sig")
            if prev_sig and prev_sig != sig:
                raise ValueError(f"La configuración de los bots cambió desde que empezó esta simulación ({prev_sig} → {sig}). "
                                 "Para no mezclar resultados de reglas distintas, reinicia con fresh=true")
        ledger.set_meta("config_sig", sig)
        eng = Engine(ledger, bots_cfg, capital, interval, portfolio_risk=portfolio_risk)
        if resumed:
            if not eng.has_saved_state():
                raise ValueError("El estado guardado está incompleto")
            eng.load_state()
        frames = _frames(feed, source, eng.symbols, interval, ledger, synthetic_advance)
        ledger.set_meta("source", label)
        ledger.set_meta("mode", "cloud")
        ledger.set_meta("interval", interval)
        ledger.set_meta("portfolio_capital", capital)
        if sim:                                                    # identidad de esta simulación (la muestra el tablero)
            ledger.set_meta("sim", json.dumps(sim, ensure_ascii=False))
        n = eng.process_new(frames)
        # la ventana completa de velas alimenta los gráficos de precio y las estimaciones de tendencia
        ledger.upsert_bars([(s_, int(r.ts), float(r.open), float(r.high), float(r.low), float(r.close), float(r.volume))
                            for s_, df in frames.items() for r in df.reset_index().itertuples(index=False)])
        ledger.prune_bars(800)
        ledger.compact_equity(int(ledger.get_meta("last_ts", 0) or 0), INTERVAL_MS[interval])
        _write(out / "ledger.json", ledger.dump())
        bench = benchmarks_from_feed(feed) if source != "synthetic" else None
        fng = fetch_fear_greed(getattr(feed, "session", None)) if source != "synthetic" else None
        _write(out / "dashboard.json", build_dashboard(metrics.load_all(ledger.con), now_ms, benchmarks=bench, fear_greed=fng))
        status.update(ok=True, bars_processed=n, resumed=resumed, source=label,
                      message=f"{n} barra(s) nueva(s) procesada(s)" if n else "Sin barras nuevas desde la última corrida")
        code = 0
    except DataUnavailable as e:
        status["message"], code = str(e), 2
    except Exception as e:
        status["message"], code = f"{type(e).__name__}: {e}", 1
    finally:
        if ledger is not None:
            ledger.close()
        for ext in ("", "-wal", "-shm"):
            Path(str(db) + ext).unlink(missing_ok=True)
    _write(out / "status.json", status)
    return code, status
