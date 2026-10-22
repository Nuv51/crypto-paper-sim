"""Compara un summary.json recién calculado con el publicado en la rama backtest-2025 / backtest-2026 (misma corrida, deben coincidir).

  python scripts/backtest_verify.py 2025|2026 actual|dinamico|indexado NUEVO_summary.json
"""
from __future__ import annotations

import json
import subprocess
import sys


def main() -> int:
    period, sim, new = sys.argv[1:4]
    branch = "origin/backtest-2025" if period == "2025" else "origin/backtest-2026"
    old = json.loads(subprocess.check_output(["git", "show", f"{branch}:{sim}/summary.json"], text=True))
    cur = json.load(open(new, encoding="utf-8"))
    ok = True
    for k in ("roi", "max_dd", "fees", "n_trades", "equity"):
        a, b = old[k], cur[k]
        same = abs(a - b) <= 1e-6 * max(1.0, abs(a)) if isinstance(a, float) else a == b
        print(f"{k}: publicado {a} · nuevo {b} · {'OK' if same else 'DIFERENTE'}")
        ok &= bool(same)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
