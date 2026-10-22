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

from sim.backtest import ArchiveHistoricFeed, HistoricFeed, run_backtest

NOTES = [
    "V2 · núcleo low cost (DCA, carry, estables, índice trimestral) + satélites gemelos (con y sin interruptor de volatilidad de BTC).",
    "Universo decidido con la foto de CoinMarketCap previa al 1 de enero y datos de Binance anteriores a esa fecha; exige cotizar todo el año "
    "(sesgo de supervivencia: ver BACKTEST_V2_2019_2024.md).",
    "El arbitraje XRP no se evalúa: no existe historial de libros de órdenes.",
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", required=True, type=int, choices=range(2019, 2027))
    ap.add_argument("--end", default=None, help="fin exclusivo (por defecto 1 de enero siguiente; 2026: 2026-10-11, el mismo tramo de V1)")
    ap.add_argument("--feed", choices=["archive", "kucoin"], default=None,
                    help="archive = perpetuo/funding del archivo de Binance (2019-2024) · kucoin = como V1 (reserva 2025-2026)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--export", default=None, help="carpeta donde volcar las tablas completas (análisis posterior)")
    a = ap.parse_args()
    cfg = importlib.import_module(f"config_v2_{a.year}")
    ident = dict(id=f"btv2-{a.year}", name=f"Backtest V2 · {a.year}", desc="Reestructurado low cost · velas de 1 h", notes=NOTES)
    end = a.end or ("2026-10-11" if a.year == 2026 else f"{a.year + 1}-01-01")
    kind = a.feed or ("kucoin" if a.year >= 2025 else "archive")
    feed = (HistoricFeed if kind == "kucoin" else ArchiveHistoricFeed)(cache_dir=f"{a.out}/cache")
    if a.year >= 2025:
        ident["name"] = f"Reserva V2 · {a.year}"
        ident["notes"] = NOTES + ["Reserva (2025-2026): perpetuo y funding de KuCoin, igual que V1, para comparar en las mismas condiciones."]
    s = run_backtest(cfg, ident, a.out, f"{a.year}-01-01", end, feed=feed, export_dir=a.export)
    print(f"OK {ident['name']}: ROI {s['roi']:+.2f}% · caída máx {s['max_dd']:.2f}% · {s['n_trades']} operaciones · comisiones {s['fees']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
