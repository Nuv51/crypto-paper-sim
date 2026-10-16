#!/usr/bin/env python
"""Mensajes para el celular/reloj/tablet a partir de dashboard.json y status.json (solo texto, sin llaves).

  python scripts/digest.py trades --old viejo.json --new nuevo.json     # operaciones y alertas nuevas (vacío si no hay)
  python scripts/digest.py digest --dashboard d.json --status s.json    # resumen del portafolio y de cada bot
  python scripts/digest.py table  --dashboard d.json                    # tabla markdown para el resumen del job

Todo es dinero FICTICIO. Las horas se muestran en la zona de TZ_NAME (por defecto America/Mexico_City).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo(os.environ.get("TZ_NAME", "America/Mexico_City"))
except Exception:                                    # sin base de zonas horarias: UTC
    TZ = timezone.utc

REASONS = {
    "stop": "Stop", "take_profit": "Take profit", "mean_reached": "Media alcanzada", "time_stop": "Salida por tiempo",
    "trailing_stop": "Trailing stop", "trend_end": "Fin de tendencia", "trend_up": "Tendencia alcista", "dca": "Compra DCA",
    "grid_buy": "Grid: compra", "grid_sell": "Grid: venta", "grid_break_down": "Ruptura bajista", "grid_break_up": "Ruptura alcista",
    "rsi_bb_oversold": "Sobreventa RSI+Bollinger", "stop_atr": "Stop ATR", "false_breakout": "Falsa ruptura",
    "channel_exit": "Salida de canal", "donchian_breakout": "Ruptura Donchian", "risk_halt": "Control de riesgo",
    "carry_open": "Abre carry", "funding": "Funding", "funding_negative": "Funding negativo", "margin_stress": "Estrés de margen",
    "peg_deviation": "Desvío del peg", "peg_restored": "Peg restablecido", "depeg_exit": "Salida por de-peg",
    "mm_init": "Inventario inicial", "mm_bid": "MM compra", "mm_ask": "MM venta", "mm_rebalance": "MM rebalanceo",
    "ml_signal": "Señal ML", "signal_flip": "Señal invertida", "rebalance_xrp_rail": "Rebalanceo XRP",
}
VENUE = {"bitso": "Bitso", "binance": "Binance", "kucoin": "KuCoin"}
T = {"ts": 0, "bot": 1, "ex": 2, "sym": 3, "side": 4, "kind": 5, "qty": 6, "price": 7, "notional": 8, "fee": 9, "pnl": 10, "reason": 11}


def load(path):
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def money(x, d=0, sign=False):
    if x is None:
        return "—"
    return f"{x:+,.{d}f}" if sign else f"{x:,.{d}f}"


def pct(x, d=1):
    return "—" if x is None else f"{x:+.{d}f}%"


def reason(r):
    if r in REASONS:
        return REASONS[r]
    if r and "->" in r:
        a, b = r.split("->", 1)
        return f"{VENUE.get(a, a)} → {VENUE.get(b, b)}"
    return r or ""


def sym_short(s):
    return s.replace("USDT~PERP", " perp").replace("~RAIL", "").replace("USDT", "")


def hhmm(ms):
    return datetime.fromtimestamp(ms / 1000, TZ).strftime("%H:%M")


def side_label(side, kind):
    if kind == "perp":
        return "abre corto" if side == "buy" else "cierra corto"
    if kind == "arb":
        return "arbitraje"
    return "compra" if side == "buy" else "venta"


def cmd_trades(a) -> int:
    new, old = load(a.new), load(a.old)
    if not new:
        return 0
    names = {b["id"]: b["name"] for b in new["bots"]}
    out = []
    if old:
        n_new = new["trades"]["total"] - old["trades"]["total"]
        rows = new["trades"]["rows"][-n_new:] if n_new > 0 else []
        rows = [r for r in rows if r[T["kind"]] != "funding"]
        by_bot = {}
        for r in rows:
            by_bot.setdefault(r[T["bot"]], []).append(r)
        for bid, rs in by_bot.items():
            if len(rs) > 3:                                   # muchas operaciones (p.ej. market making): una sola línea
                buys = sum(1 for r in rs if r[T["side"]] == "buy")
                pnl = sum(r[T["pnl"]] for r in rs)
                out.append(f"{names.get(bid, bid)}: {len(rs)} operaciones ({buys} compras / {len(rs) - buys} ventas) · "
                           f"P&L {money(pnl, 2, True)}")
                continue
            for r in rs:
                realized = r[T["side"]] == "sell" or (r[T["kind"]] in ("perp", "arb") and r[T["pnl"]])
                pnl = f" · P&L {money(r[T['pnl']], 2, True)}" if realized else ""
                out.append(f"{hhmm(r[T['ts']])} {names.get(bid, bid)}: {side_label(r[T['side']], r[T['kind']])} "
                           f"{sym_short(r[T['sym']])} @ {money(r[T['price']], 4 if r[T['price']] < 10 else 2)} "
                           f"({reason(r[T['reason']])}){pnl}")
        last = old["kpis"]["last_ts"]
        alerts = [e for e in new["events"] if e[2] == "alert" and e[0] > last]
        out += [f"⚠ {names.get(e[1], e[1])}: {e[3]}" for e in reversed(alerts)]
    if not out:
        return 0
    if len(out) > 12:
        out = out[:12] + [f"… y {len(out) - 12} más"]
    k = new["kpis"]
    print("\n".join(out + ["", f"Portafolio: {money(k['equity'])} USDT ({money(k['pnl'], 0, True)}, {pct(k['roi'], 2)}) · dinero ficticio"]))
    return 0


def equity_at(d, ms_back):
    ts, tot = d["series"]["ts"], d["series"]["total"]
    target = ts[-1] - ms_back
    i = min(range(len(ts)), key=lambda j: abs(ts[j] - target))
    return tot[i], ts[i]


def cmd_digest(a) -> int:
    d, st = load(a.dashboard), load(a.status)
    now = int(time.time() * 1000)
    lines = []
    if st and st.get("ts") and (now - st["ts"]) > 3 * 3_600_000:
        lines.append(f"⚠ El simulador no corre desde hace {(now - st['ts']) / 3_600_000:.0f} h (revisa la pestaña Actions).")
    if st and st.get("ok") is False:
        lines.append(f"⚠ Última corrida con falla: {st.get('message', '')[:140]}")
    if not d:
        print("\n".join(lines + ["Sin datos todavía."]))
        return 0
    k, bots = d["kpis"], d["bots"]
    base, base_ts = equity_at(d, 24 * 3_600_000)
    d24 = k["equity"] - base if (d["series"]["ts"][-1] - base_ts) >= 20 * 3_600_000 else None
    lines += [f"Equity {money(k['equity'])} de {money(k['capital'])} USDT · P&L {money(k['pnl'], 0, True)} ({pct(k['roi'], 2)})",
              f"24 h: {money(d24, 0, True)} · Peor caída: {k['max_dd']:.1f}% · Operaciones: {k['n_trades']}"]
    if k.get("btc_ret") is not None:
        lines.append(f"BTC en el mismo periodo: {pct(k['btc_ret'])}")
    lines.append("")
    for b in sorted(bots, key=lambda b: -(b["pnl"] or 0)):
        flag = {"paused": " ⏸", "halted": " ⛔"}.get(b["status"], "")
        lines.append(f"{b['name']}: {money(b['pnl'], 1, True)} ({pct(b['roi'], 2)}) · {b['n_trades']} ops{flag}")
    lines += ["", "Simulación con dinero ficticio; resultados pasados no garantizan resultados futuros."]
    print("\n".join(lines))
    return 0


def cmd_table(a) -> int:
    d = load(a.dashboard)
    if not d:
        return 0
    print("| Bot | Equity | P&L | ROI | Ops | Estado |\n|---|--:|--:|--:|--:|---|")
    for b in d["bots"]:
        det = (b["status_detail"] or "").replace("|", "/")[:90]
        print(f"| {b['name']} | {money(b['equity'], 1)} | {money(b['pnl'], 1, True)} | {pct(b['roi'], 2)} | {b['n_trades']} | {b['status']}: {det} |")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("trades")
    t.add_argument("--old")
    t.add_argument("--new", required=True)
    t.set_defaults(fn=cmd_trades)
    g = sub.add_parser("digest")
    g.add_argument("--dashboard", required=True)
    g.add_argument("--status")
    g.set_defaults(fn=cmd_digest)
    b = sub.add_parser("table")
    b.add_argument("--dashboard", required=True)
    b.set_defaults(fn=cmd_table)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
