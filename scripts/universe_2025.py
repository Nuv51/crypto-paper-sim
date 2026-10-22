"""Datos de Binance para armar el universo del indexado COMO SI HOY FUERA 2025-01-01 (solo lectura, APIs públicas, sin llaves).

  python scripts/universe_2025.py --candidates BTC,ETH,... --out universe_2025.json

Por moneda <MONEDA>USDT devuelve, solo con datos de Binance:
  first_day     fecha de la primera vela diaria (historial: se exige >= 365 días ANTES del 2025-01-01)
  days_2025     velas diarias de 2025 (si faltan, la moneda dejó de cotizar o tiene huecos: no se puede simular todo el año)
  close_2024    cierre del 2024-12-31 (precio del que se parte)
  vol30_2024    volumen promedio diario en USDT de los 30 días previos al 2025-01-01 (nivel de liquidez de ESE momento)
  last_close    último cierre disponible (solo para derivar suministros aproximados con la capitalización de hoy)
Nada de esto mira precios de 2025 para decidir quién entra: el universo se decide con los datos de antes del 2025-01-01.
"""
from __future__ import annotations

import argparse
import calendar
import json
import sys
import time

import requests

BASE = "https://data-api.binance.vision"
MS = 86_400_000
T_2025 = 1735689600000          # 2025-01-01 00:00 UTC
T_2026 = 1767225600000          # 2026-01-01 00:00 UTC


def to_ms(day: str) -> int:
    return int(calendar.timegm(time.strptime(day, "%Y-%m-%d")) * 1000)


def klines(s: requests.Session, sym: str, **p):
    r = s.get(f"{BASE}/api/v3/klines", params={"symbol": sym, "interval": "1d", **p}, timeout=30)
    if r.status_code == 400:                              # símbolo inexistente
        return None
    r.raise_for_status()
    return r.json()


def profile(s: requests.Session, base: str, t0: int = T_2025, t1: int = T_2026) -> dict:
    sym = base + "USDT"
    first = klines(s, sym, startTime=0, limit=1)
    if not first:
        return {"status": "NO_EXISTE"}
    out = {"status": "OK", "first_day": time.strftime("%Y-%m-%d", time.gmtime(first[0][0] / 1000))}
    y25 = klines(s, sym, startTime=t0, endTime=t1 - 1, limit=400) or []
    out["days_2025"] = out["days_period"] = len(y25)          # días con vela dentro del periodo [t0, t1)
    pre = klines(s, sym, startTime=t0 - 31 * MS, endTime=t0 - 1, limit=40) or []
    if pre:
        out["close_2024"] = out["close_pre"] = float(pre[-1][4])
        v = [float(k[7]) for k in pre[-30:]]
        out["vol30_2024"] = out["vol30_pre"] = round(sum(v) / len(v), 0)
    last = klines(s, sym, limit=2) or []
    out["last_close"] = float(last[-1][4]) if last else None
    out["last_day"] = time.strftime("%Y-%m-%d", time.gmtime(last[-1][0] / 1000)) if last else None
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--asof", default="2025-01-01", help="inicio del periodo (UTC); el historial y la liquidez se miden ANTES de esta fecha")
    ap.add_argument("--end", default="2026-01-01", help="fin del periodo (exclusivo)")
    a = ap.parse_args()
    s = requests.Session()
    out = {}
    for base in [c.strip().upper() for c in a.candidates.split(",") if c.strip()]:
        try:
            out[base] = profile(s, base, to_ms(a.asof), to_ms(a.end))
        except Exception as e:
            out[base] = {"status": "ERROR", "error": f"{type(e).__name__}: {e}"[:200]}
        print(base, out[base], flush=True)
        time.sleep(0.2)
    json.dump(out, open(a.out, "w", encoding="utf-8"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
