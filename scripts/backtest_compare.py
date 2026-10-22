"""Compara los resultados de dos periodos del backtest (2025 completo vs reserva 2026) lado a lado.

  python scripts/backtest_compare.py DIR_2025 DIR_2026 OUT.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ORDER = ["actual", "dinamico", "indexado"]


def _load(root: Path) -> dict:
    return {n: json.loads((root / n / "summary.json").read_text(encoding="utf-8")) for n in ORDER if (root / n / "summary.json").exists()}


def p(x, sign=True):
    return "—" if x is None else (f"{x:+.1f}%" if sign else f"{x:.1f}%")


def build(a: dict, b: dict) -> str:
    L = ["# Backtest en frío: 2025 vs reserva 2026", "",
         "2025 = año completo (8,760 h). 2026 = 1 ene → 10 oct (283 días). Mismos parámetros; el indexado usa el universo de cada fecha de inicio. "
         "Los periodos no tienen la misma duración: compara signos y órdenes de magnitud, no décimas.", "",
         "## Por simulador", "", "| Simulador | ROI 2025 | ROI 2026 | Caída máx. 2025 | Caída máx. 2026 | ROI−BTC 2025 | ROI−BTC 2026 |", "|---|---|---|---|---|---|---|"]
    for n in ORDER:
        if n in a and n in b:
            x, y = a[n], b[n]
            d = lambda s: None if s["btc_roi"] is None else s["roi"] - s["btc_roi"]
            L.append(f"| {n} | {p(x['roi'])} | {p(y['roi'])} | {p(-abs(x['max_dd']), False)} | {p(-abs(y['max_dd']), False)} | {p(d(x))} | {p(d(y))} |")
    ra, rb = next(iter(a.values())), next(iter(b.values()))
    L += ["", f"Referencias: BTC {p(ra['btc_roi'])} → {p(rb['btc_roi'])} · ETH {p(ra['eth_roi'])} → {p(rb['eth_roi'])} · Mercado {p(ra['market_roi'])} → {p(rb['market_roi'])} (2025 → 2026)."]
    for n in ORDER:
        if n not in a or n not in b:
            continue
        L += ["", f"## Bots · {n}", "", "| Bot | ROI 2025 | ROI 2026 | ¿Mismo signo? |", "|---|---|---|---|"]
        mb = {k["name"]: k for k in b[n]["bots"]}
        for k in a[n]["bots"]:
            o = mb.get(k["name"])
            if o is None:
                continue
            same = "—" if abs(k["roi"]) < 0.5 or abs(o["roi"]) < 0.5 else ("sí" if (k["roi"] > 0) == (o["roi"] > 0) else "NO")
            L.append(f"| {k['name']} | {p(k['roi'])} | {p(o['roi'])} | {same} |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    Path(sys.argv[3]).write_text(build(_load(Path(sys.argv[1])), _load(Path(sys.argv[2]))), encoding="utf-8")
    print("comparación escrita")
