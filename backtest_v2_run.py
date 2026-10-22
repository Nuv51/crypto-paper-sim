#!/usr/bin/env python
"""Backtest en frío V2 (Reestructurado low cost) de UN año (ver BACKTEST_V2_2019_2024.md). Lo ejecuta el flujo `backtest-v2`.

  python backtest_v2_run.py --year 2021 --out out/2021 [--export out/2021/tables]

Salida: <out>/dashboard.json y <out>/summary.json. Perpetuo y funding: archivo público de futuros de Binance (desde 2020-01).
Códigos: 0 ok · 1 error (datos faltantes, etc.; se corrige el CÓDIGO, nunca los parámetros).
"""
from __future__ import annotations

import argparse
import importlib
import sys

from sim.backtest import ArchiveHistoricFeed, run_backtest

NOTES = [
    "V2 · núcleo low cost (DCA, carry, estables, índice trimestral) + satélites gemelos (con y sin interruptor de volatilidad de BTC).",
    "Universo decidido con la foto de CoinMarketCap previa al 1 de enero y datos de Binance anteriores a esa fecha; exige cotizar todo el año "
    "(sesgo de supervivencia: ver BACKTEST_V2_2019_2024.md).",
    "El arbitraje XRP no se evalúa: no existe historial de libros de órdenes.",
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", required=True, type=int, choices=range(2019, 2025))
    ap.add_argument("--out", required=True)
    ap.add_argument("--export", default=None, help="carpeta donde volcar las tablas completas (análisis posterior)")
    a = ap.parse_args()
    cfg = importlib.import_module(f"config_v2_{a.year}")
    ident = dict(id=f"btv2-{a.year}", name=f"Backtest V2 · {a.year}", desc="Reestructurado low cost · velas de 1 h", notes=NOTES)
    feed = ArchiveHistoricFeed(cache_dir=f"{a.out}/cache")
    s = run_backtest(cfg, ident, a.out, f"{a.year}-01-01", f"{a.year + 1}-01-01", feed=feed, export_dir=a.export)
    print(f"OK {ident['name']}: ROI {s['roi']:+.2f}% · caída máx {s['max_dd']:.2f}% · {s['n_trades']} operaciones · comisiones {s['fees']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
