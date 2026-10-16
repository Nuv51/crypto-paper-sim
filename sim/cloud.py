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
from .data import MarketFeed, SyntheticFeed, INTERVAL_MS
from .engine import Engine
from .export import build_dashboard
from .ledger import Ledger

WINDOW = 700


class DataUnavailable(Exception):
    pass


BENCH_SYMBOLS = ("BTCUSDT", "ETHUSDT")


def benchmarks_from_feed(feed) -> Optional[dict]:
    """Historia de BTC y ETH para comparar el portafolio en periodos largos (día, semana, mes, 3 meses, año).

    Velas horarias de ~32 días y diarias de 365. A la serie diaria se le agrega el último cierre horario para que el
    rendimiento llegue "hasta ahora" y no hasta el cierre de ayer. Es OPCIONAL: si algo falla devuelve None y el
    tablero simplemente no ofrece los periodos largos; nunca hace fallar la corrida.
    """
    if not hasattr(feed, "latest_closed"):
        return None
    out: dict = {}
    try:
        for sym in BENCH_SYMBOLS:
            h = feed.latest_closed(sym, "1h", 768)
            time.sleep(getattr(feed, "pause", 0))
            d = feed.latest_closed(sym, "1d", 365)
            time.sleep(getattr(feed, "pause", 0))
            if h.empty or d.empty:
                return None
            dts = [int(t) for t in d.index]
            dcl = [float(v) for v in d["close"]]
            if int(h.index[-1]) > dts[-1]:
                dts.append(int(h.index[-1]))
                dcl.append(float(h["close"].iloc[-1]))
            out[sym] = {"h": {"ts": [int(t) for t in h.index], "close": [round(float(v), 4) for v in h["close"]]},
                        "d": {"ts": dts, "close": [round(v, 4) for v in dcl]}}
    except Exception:
        return None
    return out


def config_signature(bots_cfg: list[dict], capital: float) -> str:
    """Huella de la configuración. Si cambia a mitad de una simulación, no se mezclan resultados de reglas distintas."""
    blob = json.dumps({"capital": capital, "bots": bots_cfg}, sort_keys=True, default=str)
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
             source: str = "binance", feed=None, synthetic_advance: int = 24, seed: int = 7) -> tuple[int, dict]:
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
        sig = config_signature(bots_cfg, capital)
        if resumed:
            prev_sig = ledger.get_meta("config_sig")
            if prev_sig and prev_sig != sig:
                raise ValueError(f"La configuración de los bots cambió desde que empezó esta simulación ({prev_sig} → {sig}). "
                                 "Para no mezclar resultados de reglas distintas, reinicia con fresh=true")
        ledger.set_meta("config_sig", sig)
        eng = Engine(ledger, bots_cfg, capital, interval)
        if resumed:
            if not eng.has_saved_state():
                raise ValueError("El estado guardado está incompleto")
            eng.load_state()
        frames = _frames(feed, source, eng.symbols, interval, ledger, synthetic_advance)
        ledger.set_meta("source", label)
        ledger.set_meta("mode", "cloud")
        ledger.set_meta("interval", interval)
        ledger.set_meta("portfolio_capital", capital)
        n = eng.process_new(frames)
        # la ventana completa de velas alimenta los gráficos de precio y las estimaciones de tendencia
        ledger.upsert_bars([(s_, int(r.ts), float(r.open), float(r.high), float(r.low), float(r.close), float(r.volume))
                            for s_, df in frames.items() for r in df.reset_index().itertuples(index=False)])
        ledger.prune_bars(800)
        _write(out / "ledger.json", ledger.dump())
        bench = benchmarks_from_feed(feed) if source != "synthetic" else None
        _write(out / "dashboard.json", build_dashboard(metrics.load_all(ledger.con), now_ms, benchmarks=bench))
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
