#!/usr/bin/env python
"""Backtest en frío V3 de UN año y UNA variante (ver BACKTEST_V3.md). Lo ejecuta el flujo `backtest-v3`.

  python backtest_v3_run.py --year 2021 --variant v3|ref --out out/v3-2021 [--export out/v3-2021/tables]

  v3  = núcleo con filtro de tendencia (BTC sobre su media de 200 días) en DCA e índice
  ref = mismo portafolio SIN filtro (control para medir el efecto del filtro)
Códigos: 0 ok · 1 error (datos faltantes, etc.; se corrige el CÓDIGO, nunca los parámetros).
"""
from __future__ import annotations

import argparse
import importlib
import sys

from sim.backtest import ArchiveHistoricFeed, HistoricFeed, run_backtest

NOTES = [
    "V3 · núcleo low cost sin satélites ni estables: DCA, índice Top-25 trimestral y carry BTC/ETH con más peso; 10 % en efectivo.",
    "Universo y parámetros heredados de V2 (foto de CoinMarketCap previa al 1 de enero). Sesgo de supervivencia: ver BACKTEST_V2_2019_2024.md §6.",
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", required=True, type=int, choices=range(2019, 2027))
    ap.add_argument("--variant", required=True, choices=["v3", "ref"])
    ap.add_argument("--end", default=None)
    ap.add_argument("--feed", choices=["archive", "kucoin"], default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--export", default=None)
    a = ap.parse_args()
    mod = "config_v3" if a.variant == "v3" else "config_v3ref"
    cfg = importlib.import_module(f"{mod}_{a.year}")
    label = "V3" if a.variant == "v3" else "V3-ref (sin filtro)"
    ident = dict(id=f"bt{a.variant}-{a.year}", name=f"Backtest {label} · {a.year}", desc="Núcleo low cost · velas de 1 h", notes=NOTES)
    end = a.end or ("2026-10-11" if a.year == 2026 else f"{a.year + 1}-01-01")
    kind = a.feed or ("kucoin" if a.year >= 2025 else "archive")
    feed = (HistoricFeed if kind == "kucoin" else ArchiveHistoricFeed)(cache_dir=f"{a.out}/cache")
    if a.year >= 2025:
        ident["notes"] = NOTES + ["Reserva (2025-2026): perpetuo y funding de KuCoin, igual que V1/V2-reserva."]
    s = run_backtest(cfg, ident, a.out, f"{a.year}-01-01", end, feed=feed, export_dir=a.export)
    print(f"OK {ident['name']}: ROI {s['roi']:+.2f}% · caída máx {s['max_dd']:.2f}% · {s['n_trades']} operaciones · comisiones {s['fees']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
