"""Verifica qué monedas candidatas se pueden usar en el simulador indexado (solo lectura, APIs públicas, sin llaves).

  python scripts/universe_check.py --candidates BTC,ETH,... --out universe_check.json     # sondeo completo (manual)
  python scripts/universe_check.py --config config_index --out universe_status.json       # solo estado (cada corrida)

Para cada símbolo <MONEDA>USDT consulta Binance spot (data-api.binance.vision):
  · status == TRADING en exchangeInfo (si no, no se puede operar)
  · cuántas velas diarias hay (sondeo completo): el índice exige >= 365 días de historia
  · volumen promedio diario en USDT de los últimos 30 días (sondeo completo): decide el slippage por nivel de liquidez
Salida 0 si todo bien; 1 si algún símbolo de la configuración dejó de estar en TRADING (modo --config).
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
import time

import requests

BASE = "https://data-api.binance.vision"


def trading_symbols(session: requests.Session) -> dict:
    r = session.get(f"{BASE}/api/v3/exchangeInfo", timeout=60)
    r.raise_for_status()
    return {s["symbol"]: s["status"] for s in r.json()["symbols"] if s.get("quoteAsset") == "USDT"}


def daily_profile(session: requests.Session, symbol: str) -> dict:
    r = session.get(f"{BASE}/api/v3/klines", params={"symbol": symbol, "interval": "1d", "limit": 400}, timeout=30)
    r.raise_for_status()
    rows = r.json()
    vols = [float(k[7]) for k in rows[-31:-1]]                  # quote volume de los últimos 30 días cerrados
    return {"days": len(rows), "first_ms": int(rows[0][0]) if rows else None,
            "avg_vol_usdt_30d": round(sum(vols) / len(vols), 0) if vols else None,
            "last_close": float(rows[-1][4]) if rows else None}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidates", help="monedas separadas por coma (sin USDT)")
    ap.add_argument("--config", help="módulo de configuración con UNIVERSE (modo estado)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    s = requests.Session()
    status = trading_symbols(s)
    out: dict = {}
    if a.candidates:
        for base in [c.strip().upper() for c in a.candidates.split(",") if c.strip()]:
            sym = base + "USDT"
            row = {"status": status.get(sym, "NO_EXISTE")}
            if row["status"] == "TRADING":
                try:
                    row.update(daily_profile(s, sym))
                except Exception as e:
                    row["error"] = f"{type(e).__name__}: {e}"[:200]
                time.sleep(0.15)
            out[sym] = row
            print(sym, row, flush=True)
        json.dump(out, open(a.out, "w", encoding="utf-8"), indent=1)
        return 0
    cfg = importlib.import_module(a.config)
    bad = {}
    for sym in cfg.UNIVERSE_SYMBOLS:
        st = status.get(sym, "NO_EXISTE")
        out[sym] = st
        if st != "TRADING":
            bad[sym] = st
    json.dump({"checked": len(out), "not_trading": bad, "ts": int(time.time() * 1000)}, open(a.out, "w", encoding="utf-8"), indent=1)
    print(f"{len(out)} símbolos revisados; fuera de TRADING: {bad or 'ninguno'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
