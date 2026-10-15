#!/usr/bin/env python
"""CLI del simulador (dinero ficticio, precios reales).

  python run.py replay --days 120                  # historial REAL de Binance (API pública), a toda velocidad
  python run.py replay --days 120 --source synthetic  # datos inventados: solo para probar el código
  python run.py live --poll 60                     # forward test: procesa cada vela nueva (Ctrl+C para detener)
  python run.py report                             # resumen en consola de una base existente

Las bases viven en data/*.db. El dashboard (streamlit run dashboard.py) lee la misma base.
Opcional: exporta CMC_API_KEY para activar la verificación cruzada de precios con CoinMarketCap.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

import config
from sim import metrics
from sim.data import BinanceFeed, CoinMarketCapQuotes, SyntheticFeed, INTERVAL_MS
from sim.engine import Engine
from sim.ledger import Ledger, read_only_connection


def _only(arg):
    return [x.strip() for x in arg.split(",")] if arg else None


def cmd_replay(a) -> int:
    db = Path(a.db)
    if db.exists():
        if not a.fresh:
            print(f"{db} ya existe. Usa --fresh para sobrescribirlo (replay siempre empieza de cero).")
            return 1
        for ext in ("", "-wal", "-shm"):
            Path(str(db) + ext).unlink(missing_ok=True)
    ledger = Ledger(db)
    eng = Engine(ledger, config.BOTS, a.capital, config.INTERVAL, only=_only(a.only))
    feed = SyntheticFeed(seed=a.seed) if a.source == "synthetic" else BinanceFeed()
    bar_ms = INTERVAL_MS[config.INTERVAL]
    extra = math.ceil(eng.max_warmup * bar_ms / 86_400_000) + 1
    print(f"Fuente: {feed.label}")
    print(f"Descargando/leyendo {a.days} días (+{extra} de calentamiento) de {len(eng.symbols)} monedas…")
    frames = {}
    for s in eng.symbols:
        frames[s] = feed.history(s, config.INTERVAL, a.days + extra)
        print(f"  {s}: {len(frames[s])} velas")
    ledger.set_meta("source", feed.label)
    ledger.set_meta("mode", "replay")
    ledger.set_meta("interval", config.INTERVAL)
    ledger.set_meta("portfolio_capital", a.capital)
    info = eng.replay(frames)
    print(f"Listo: {info['bars']} barras simuladas.\n")
    ledger.close()
    print(metrics.format_report(metrics.load_all(read_only_connection(db))))
    return 0


def cmd_live(a) -> int:
    ledger = Ledger(a.db)
    eng = Engine(ledger, config.BOTS, a.capital, config.INTERVAL, only=_only(a.only))
    if eng.has_saved_state():
        eng.load_state()
        print("Reanudando simulación guardada.")
    else:
        print("Nueva simulación live (empieza con la última vela cerrada).")
        ledger.set_meta("capital_note", "dinero ficticio")
    feed = BinanceFeed()
    ledger.set_meta("source", feed.label)
    ledger.set_meta("mode", "live")
    ledger.set_meta("interval", config.INTERVAL)
    ledger.set_meta("portfolio_capital", a.capital)
    cmc = None
    if os.environ.get("CMC_API_KEY"):
        cmc = CoinMarketCapQuotes()
        print("Verificación cruzada con CoinMarketCap activada.")
    print(f"Procesando cada {a.poll}s. Ctrl+C para detener (el estado queda guardado).")
    try:
        eng.live(feed, poll_seconds=a.poll, cmc=cmc)
    except KeyboardInterrupt:
        eng.flush()
        eng.save_state()
        print("\nDetenido. Estado guardado.")
    finally:
        ledger.close()
    return 0


def cmd_report(a) -> int:
    if not Path(a.db).exists():
        print(f"No existe {a.db}")
        return 1
    print(metrics.format_report(metrics.load_all(read_only_connection(a.db))))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--db", default="data/paper.db")
        p.add_argument("--capital", type=float, default=config.PORTFOLIO_CAPITAL,
                       help="capital ficticio total del portafolio (USDT)")
        p.add_argument("--only", help="ids o tipos de bot separados por coma (p.ej. grid,trend)")

    r = sub.add_parser("replay", help="simula sobre historial a toda velocidad")
    common(r)
    r.add_argument("--days", type=int, default=120)
    r.add_argument("--source", choices=["binance", "synthetic"], default="binance")
    r.add_argument("--seed", type=int, default=7, help="semilla del feed sintético")
    r.add_argument("--fresh", action="store_true", help="sobrescribe la base si existe")
    r.set_defaults(fn=cmd_replay)

    l = sub.add_parser("live", help="forward test con velas nuevas (resumible)")
    common(l)
    l.add_argument("--poll", type=int, default=60, help="segundos entre consultas")
    l.set_defaults(fn=cmd_live)

    p = sub.add_parser("report", help="resumen en consola")
    p.add_argument("--db", default="data/paper.db")
    p.set_defaults(fn=cmd_report)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
