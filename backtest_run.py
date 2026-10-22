#!/usr/bin/env python
"""Backtest en frío de UN simulador (ver BACKTEST_2025.md). Lo ejecuta el flujo `backtest-2025`; no toca los simuladores en vivo.

  python backtest_run.py --sim actual|dinamico|indexado --out out/actual [--start 2025-01-01 --end 2026-01-01]

Salida: <out>/dashboard.json (formato del tablero) y <out>/summary.json (cifras fijadas de antemano).
Códigos: 0 ok · 1 error (datos faltantes, etc.; se corrige el CÓDIGO, nunca los parámetros).
"""
from __future__ import annotations

import argparse
import importlib
import sys

from sim.backtest import run_backtest

NOTE_XRP = "El bot de arbitraje XRP no se puede evaluar: no existe historial de libros de órdenes de Bitso/Binance/KuCoin."
SIMS = {
    "actual": ("config", dict(id="bt-actual", name="Backtest 2025 · Simulador actual", desc="Velas de 1 h · 10 bots · config.py sin cambios",
                              notes=[NOTE_XRP])),
    "dinamico": ("config_active", dict(id="bt-dinamico", name="Backtest 2025 · Simulador dinámico",
                                       desc="Velas de 15 min · 14 bots · config_active.py sin cambios", notes=[NOTE_XRP])),
    "indexado": ("config_index_2025", dict(id="bt-indexado", name="Backtest 2025 · Simulador indexado",
                                           desc="3 índices con el universo punto-en-el-tiempo del 2025-01-01 (config_index_2025.py)", notes=[])),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sim", required=True, choices=sorted(SIMS))
    ap.add_argument("--out", required=True)
    ap.add_argument("--start", default="2025-01-01")
    ap.add_argument("--end", default="2026-01-01")
    a = ap.parse_args()
    module, ident = SIMS[a.sim]
    cfg = importlib.import_module(module)
    s = run_backtest(cfg, ident, a.out, a.start, a.end)
    print(f"OK {ident['name']}: ROI {s['roi']:+.2f}% · caída máx {s['max_dd']:.2f}% · {s['n_trades']} operaciones · comisiones {s['fees']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
