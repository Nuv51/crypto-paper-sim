#!/usr/bin/env python
"""Un paso incremental del simulador para la nube (lo ejecuta cada corrida de la tarea programada).

  python cloud_step.py --state in/ledger.json --out out          # datos reales de Binance (API pública)
  python cloud_step.py --state in/ledger.json --out out --source synthetic   # SOLO pruebas

Entrada : --state  snapshot JSON del estado anterior (si no existe, es la primera corrida)
Salida  : out/ledger.json (estado nuevo) · out/dashboard.json (datos del tablero) · out/status.json
Códigos : 0 ok · 1 error inesperado · 2 sin datos/red (no se escribe ledger.json: el estado anterior sigue vigente)
"""
from __future__ import annotations

import argparse
import sys

import config
from sim.cloud import run_step


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", help="ruta del ledger.json anterior")
    ap.add_argument("--out", required=True, help="carpeta de salida")
    ap.add_argument("--source", choices=["binance", "synthetic"], default="binance")
    ap.add_argument("--capital", type=float, default=config.PORTFOLIO_CAPITAL)
    ap.add_argument("--synthetic-advance", type=int, default=24, help="(solo synthetic) velas nuevas por corrida")
    a = ap.parse_args()
    code, status = run_step(config.BOTS, config.INTERVAL, a.capital, a.state, a.out, a.source,
                            synthetic_advance=a.synthetic_advance, portfolio_risk=config.PORTFOLIO_RISK)
    print(("OK" if code == 0 else f"FALLÓ (código {code})") + f": {status['message']}")
    return code


if __name__ == "__main__":
    sys.exit(main())
