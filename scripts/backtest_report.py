"""Junta los summary.json de los tres backtests y escribe informe.md (cifras fijadas en BACKTEST_2025.md).

  python scripts/backtest_report.py DIR_CON_summary_por_simulador OUT.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ORDER = ["actual", "dinamico", "indexado"]


def fmt(x, nd=2, suf=""):
    return "—" if x is None else f"{x:+.{nd}f}{suf}" if suf == "%" else f"{x:,.{nd}f}{suf}"


def build(root: Path) -> str:
    sums = {}
    for name in ORDER:
        f = root / name / "summary.json"
        if f.exists():
            sums[name] = json.loads(f.read_text(encoding="utf-8"))
    L = ["# Backtest en frío 2025 — resultados", "",
         "Periodo 2025-01-01 → 2026-01-01 (UTC). Dinero ficticio, parámetros sin tocar, corrida única. "
         "Es *cómo se habrían comportado estas reglas*, no una promesa ni una prueba de rentabilidad. Sesgos declarados en BACKTEST_2025.md.", ""]
    any_s = next(iter(sums.values()), None)
    if any_s:
        L += ["## Referencias (comprar y mantener)", "",
              f"- BTC: {fmt(any_s['btc_roi'], 2, '%')} · ETH: {fmt(any_s['eth_roi'], 2, '%')} · Mercado (canasta de las 10 mayores): {fmt(any_s['market_roi'], 2, '%')}", ""]
    L += ["## Por simulador", "", "| Simulador | ROI | Caída máx. | Sharpe | Operaciones | Comisiones (USDT) | ROI − BTC |", "|---|---|---|---|---|---|---|"]
    for n, s in sums.items():
        diff = None if s["btc_roi"] is None else s["roi"] - s["btc_roi"]
        L.append(f"| {s['name']} | {fmt(s['roi'], 2, '%')} | {fmt(-abs(s['max_dd']), 2, '%')} | {fmt(s['sharpe'], 2)} | {s['n_trades']:,} | {s['fees']:,.0f} | {fmt(diff, 2, ' pp')} |")
    for n, s in sums.items():
        L += ["", f"## {s['name']}", "", "| Bot | Estrategia | ROI | Caída máx. | Operaciones | Comisiones | Estado |", "|---|---|---|---|---|---|---|"]
        for b in s["bots"]:
            L.append(f"| {b['name']} | {b['strategy']} | {fmt(b['roi'], 2, '%')} | {fmt(None if b['max_dd'] is None else -abs(b['max_dd']), 2, '%')} | "
                     f"{b['n_trades']:,} | {fmt(b['fees'], 0)} | {b['status']} |")
    missing = [n for n in ORDER if n not in sums]
    if missing:
        L += ["", f"**Faltan resultados de:** {', '.join(missing)}."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    Path(sys.argv[2]).write_text(build(Path(sys.argv[1])), encoding="utf-8")
    print("informe escrito")
