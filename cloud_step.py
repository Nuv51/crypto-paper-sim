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
import importlib
import sys

from sim.cloud import WINDOW, run_step

# Identidad de cada simulación (la muestra el tablero y enlaza con la otra). "actual" usa config.py; "activo" usa config_active.py.
SIMS = {
    "config": dict(id="actual", name="Simulador actual", other="activo",
                   desc="Velas de 1 h · 10 bots · umbrales conservadores"),
    "config_active": dict(id="activo", name="Simulador dinámico", other="binance",
                          desc="Velas de 15 min · más monedas · umbrales más sueltos · 14 bots"),
    "config_index": dict(id="indice", name="Simulador indexado", other="binance",
                         desc="Cartera pasiva: 3 índices (Top-25 y Top-50 por capitalización, Top-25 igual peso) con rebalanceo mensual; sin señales",
                         window=400, keep_bars=400),
}


def _ident(sim: dict) -> dict:
    """Solo la identidad que muestra el tablero (id, nombre, descripción, enlace al otro); los parámetros técnicos no."""
    return {k: v for k, v in sim.items() if k in ("id", "name", "other", "desc")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", help="ruta del ledger.json anterior")
    ap.add_argument("--out", required=True, help="carpeta de salida")
    ap.add_argument("--source", choices=["binance", "synthetic"], default="binance")
    ap.add_argument("--config", default="config", choices=sorted(SIMS), help="módulo de configuración (config | config_active | config_index)")
    ap.add_argument("--capital", type=float, default=None, help="por defecto, el PORTFOLIO_CAPITAL de la configuración")
    ap.add_argument("--synthetic-advance", type=int, default=24, help="(solo synthetic) velas nuevas por corrida")
    a = ap.parse_args()
    cfg = importlib.import_module(a.config)
    capital = cfg.PORTFOLIO_CAPITAL if a.capital is None else a.capital
    code, status = run_step(cfg.BOTS, cfg.INTERVAL, capital, a.state, a.out, a.source,
                            synthetic_advance=a.synthetic_advance, portfolio_risk=cfg.PORTFOLIO_RISK, sim=_ident(SIMS[a.config]),
                            window=SIMS[a.config].get("window", WINDOW), keep_bars=SIMS[a.config].get("keep_bars", 800))
    print(("OK" if code == 0 else f"FALLÓ (código {code})") + f": {status['message']}")
    return code


if __name__ == "__main__":
    sys.exit(main())
