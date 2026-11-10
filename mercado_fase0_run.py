#!/usr/bin/env python
"""Observatorio de mercado · FASE 0 — corrida en frío (una sola vez) según OBSERVATORIO_MERCADO.md.

  python mercado_fase0_run.py --out out/mercado-fase0                 # baja velas diarias reales de Binance (hasta 2026-10-31)
  python mercado_fase0_run.py --closes closes.csv --out out --perm 200 # desde un CSV (fecha × moneda), p. ej. para pruebas

Salida: out/results.json · out/report.md · out/closes.csv (los datos exactos usados, para auditar y repetir).
Códigos: 0 ok · 1 error · 2 sin datos/red.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

import numpy as np
import pandas as pd

import config_index
from sim import market_ranges as mr
from sim.data import BinanceFeed

END_DATE = "2026-10-31"                        # fijo: repetir la corrida da los mismos números
START_MS = int(pd.Timestamp("2017-07-01", tz="UTC").timestamp() * 1000)


def fetch_closes(symbols, end_date=END_DATE, feed=None) -> dict[str, pd.Series]:
    feed = feed or BinanceFeed(cache_dir="data/cache")
    end_ms = int((pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(days=1)).timestamp() * 1000) - 1
    out = {}
    for s in symbols:
        df = feed.fetch_klines(s, "1d", start_ms=START_MS, end_ms=end_ms)
        if df.empty:
            print(f"  {s}: sin datos", flush=True)
            continue
        df = df[df.index <= end_ms]
        ser = pd.Series(df["close"].to_numpy(), index=pd.to_datetime(df.index, unit="ms").normalize())
        ser = ser[~ser.index.duplicated(keep="last")]
        out[s] = ser
        print(f"  {s}: {len(ser)} días ({ser.index[0].date()} → {ser.index[-1].date()})", flush=True)
    return out


def _clean(x):
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        return None if not math.isfinite(float(x)) else float(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    return x


def _fmt(v, d=2, pct=False):
    if v is None:
        return "—"
    return f"{v * 100:+.{d}f}%" if pct else f"{v:.{d}f}"


def render_report(res: dict) -> str:
    p = res["params"]
    r = {lab: {h: (v[h] if h in v else v[str(h)]) for h in mr.HORIZONS} for lab, v in res["results"].items()}   # JSON vuelve las claves texto
    lines = ["# Observatorio de mercado · Fase 0 — resultados en frío", "",
             f"Datos: {len(p['monedas'])} monedas, {p['desde']} → {p['hasta']}. Permutaciones: {p['n_perm']}. Umbral descubrimiento (Bonferroni): p < {p['alfa_descubrimiento']:.4f}; confirmación: p < {p['alfa_confirmacion']}.", "",
             "Exceso = mediana del retorno tras el episodio menos la mediana de la misma moneda en el mismo periodo. "
             "Episodios de mercado = episodios agrupados a menos de 30 días entre monedas.", ""]
    n_ev = sum(1 for lab in mr.ALL_LABELS for h in mr.HORIZONS if r[lab][h]["veredicto"] == "con evidencia")
    lines += [f"**Etiquetas × horizontes con evidencia: {n_ev} de {mr.N_TESTS}.**", "",
              "| Etiqueta | h | Veredicto | Ep. mercado desc/conf | Exceso desc | p desc | Exceso conf | p conf | Mediana (todo) | % positivo |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for lab in mr.ALL_LABELS:
        for h in mr.HORIZONS:
            x = r[lab][h]
            d, c, t = x["descubrimiento"], x["confirmacion"], x["todo"]
            lines.append(f"| {mr.LABEL_TEXT[lab]} | {h} d | {x['veredicto']} | {d['n_episodios_mercado']}/{c['n_episodios_mercado']} | "
                         f"{_fmt(d['exceso'], 1, True)} | {_fmt(d['p'], 3)} | {_fmt(c['exceso'], 1, True)} | {_fmt(c['p'], 3)} | "
                         f"{_fmt(t['mediana'], 1, True)} | {_fmt(t['pct_positivo'], 0, True).replace('+', '')} |")
    lines += ["", "## Motivos", ""]
    for lab in mr.ALL_LABELS:
        for h in mr.HORIZONS:
            lines.append(f"- {mr.LABEL_TEXT[lab]} · {h} d: {r[lab][h]['veredicto']} — {r[lab][h]['motivo']}")
    lines += ["", "## Control de método: la volatilidad es persistente", ""]
    for lab, v in res["vol_control"].items():
        lines.append(f"- {mr.LABEL_TEXT[lab]}: tras el evento, la volatilidad de los 30 días siguientes es {_fmt(v['ratio_mediano_tras_evento'])}× la actual "
                     f"(base: {_fmt(v['ratio_mediano_base'])}×; {v['n_eventos']} eventos).")
    lines += ["", f"_{mr.DISCLAIMER}_", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--closes", help="CSV fecha × moneda en lugar de bajar de Binance")
    ap.add_argument("--perm", type=int, default=mr.N_PERM)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()
    if a.closes:
        df = pd.read_csv(a.closes, index_col=0, parse_dates=True)
        closes = {c: df[c].dropna() for c in df.columns}
    else:
        print("Bajando velas diarias de Binance…", flush=True)
        try:
            closes = fetch_closes(config_index.TOP25)
        except Exception as e:                                  # red caída / bloqueo
            print(f"Sin datos: {e}", file=sys.stderr)
            return 2
        if "BTCUSDT" not in closes or len(closes) < 15:
            print("Datos insuficientes (menos de 15 monedas o sin BTC)", file=sys.stderr)
            return 2
    pd.DataFrame(closes).sort_index().to_csv(os.path.join(a.out, "closes.csv"), index_label="fecha")
    print(f"Calculando ({a.perm} permutaciones por prueba)…", flush=True)

    def prog(lab, h, x):
        print(f"  {lab:20s} {h:>3d} d → {x['veredicto']}", flush=True)

    res = mr.run_phase0(closes, n_perm=a.perm, progress=prog)
    res = _clean(res)
    with open(os.path.join(a.out, "results.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, allow_nan=False)
    with open(os.path.join(a.out, "report.md"), "w", encoding="utf-8") as f:
        f.write(render_report(res))
    print(f"Listo en {time.time() - t0:.0f} s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
