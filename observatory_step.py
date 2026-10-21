#!/usr/bin/env python
"""Una corrida del observatorio de spreads (solo mide; no opera ni simula operaciones).

  python observatory_step.py --state in/stats.json --out out                 # APIs públicas reales
  python observatory_step.py --state in/stats.json --out out --snapshots 3 --interval 10

Entrada : --state  estado acumulado anterior (si no existe, es la primera corrida)
Salida  : out/stats.json (estado nuevo) · out/summary.json (resumen para tablero) · out/summary.md · out/status.json
Códigos : 0 ok · 1 error (p. ej. parámetros distintos a los del estado) · 2 sin datos/red (no se escribe stats.json:
          el estado anterior sigue vigente)

Los parámetros no se afinan a mitad de una medición: si cambian respecto al estado guardado, la corrida se niega.
Para empezar de cero, borra el estado (o usa --fresh; el anterior se conserva como stats.prev.json).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

from sim import observatory as obs


def _write(path: str, obj) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        if isinstance(obj, str):
            fh.write(obj)
        else:
            json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    os.replace(tmp, path)


def _clean(x):
    """JSON estricto: NaN/inf -> null."""
    if isinstance(x, float) and not math.isfinite(x):
        return None
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_clean(v) for v in x]
    return x


def run(state_path, out_dir, snapshots, interval, fresh=False, fetchers=None, sleep=time.sleep, params=None):
    os.makedirs(out_dir, exist_ok=True)
    params = dict(obs.DEFAULT_PARAMS if params is None else params)
    status = {"ts": int(time.time() * 1000), "snapshots_requested": snapshots}
    try:
        if state_path and os.path.exists(state_path) and not fresh:
            with open(state_path, encoding="utf-8") as fh:
                state = json.load(fh)
            if state.get("params") != params:
                status["message"] = ("Los parámetros cambiaron respecto al estado guardado; no se afinan a mitad de una medición. "
                                     "Usa --fresh para empezar de cero.")
                _write(os.path.join(out_dir, "status.json"), status)
                return 1, status
        else:
            if fresh and state_path and os.path.exists(state_path):
                os.replace(state_path, os.path.splitext(state_path)[0] + ".prev.json")
            state = obs.new_state(params)
        f = fetchers or obs.LiveFetchers()
        good = obs.observe(state, f, snapshots=snapshots, interval_s=interval, sleep=sleep)
        status["snapshots_ok"] = good
        if good == 0:
            status["message"] = "Sin datos: Bitso o los otros exchanges no respondieron en ninguna foto."
            _write(os.path.join(out_dir, "status.json"), status)
            return 2, status
        summary = _clean(obs.summarize(state))
        _write(os.path.join(out_dir, "stats.json"), _clean(state))
        _write(os.path.join(out_dir, "summary.json"), summary)
        _write(os.path.join(out_dir, "summary.md"), obs.render_markdown(summary))
        status["message"] = (f"{good}/{snapshots} fotos · {summary['days']:.1f} días acumulados · "
                             f"{len(summary['routes'])} rutas")
        _write(os.path.join(out_dir, "status.json"), status)
        return 0, status
    except Exception as e:                                         # nunca dejar un estado a medias
        status["message"] = f"Error inesperado: {type(e).__name__}: {e}"
        _write(os.path.join(out_dir, "status.json"), status)
        return 1, status


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", help="ruta del stats.json anterior")
    ap.add_argument("--out", required=True, help="carpeta de salida")
    ap.add_argument("--snapshots", type=int, default=6, help="fotos por corrida")
    ap.add_argument("--interval", type=float, default=20.0, help="segundos entre fotos")
    ap.add_argument("--fresh", action="store_true", help="empezar de cero (conserva el estado anterior como .prev)")
    a = ap.parse_args()
    code, status = run(a.state, a.out, a.snapshots, a.interval, a.fresh)
    print(("OK" if code == 0 else f"FALLÓ (código {code})") + f": {status['message']}")
    return code


if __name__ == "__main__":
    sys.exit(main())
