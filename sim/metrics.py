"""Métricas de desempeño y de solapamiento entre bots (las usan el CLI y el dashboard)."""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from .ledger import read_df


def load_all(con: sqlite3.Connection) -> dict:
    meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
    return {
        "meta": meta,
        "bots": read_df(con, "SELECT * FROM bots ORDER BY bot_id"),
        "trades": read_df(con, "SELECT * FROM trades ORDER BY ts, id"),
        "equity": read_df(con, "SELECT * FROM equity ORDER BY ts"),
        "bars": read_df(con, "SELECT * FROM bars ORDER BY symbol, ts"),
        "events": read_df(con, "SELECT * FROM events ORDER BY id DESC LIMIT 500"),
    }


def max_drawdown(eq: pd.Series) -> float:
    """Drawdown máximo como fracción negativa (p.ej. -0.08)."""
    if eq.empty:
        return 0.0
    return float((eq / eq.cummax() - 1).min())


def sharpe_daily(eq: pd.Series, ts_ms: pd.Series, min_days: int = 20) -> float:
    s = pd.Series(eq.values, index=pd.to_datetime(ts_ms.values, unit="ms", utc=True))
    d = s.resample("1D").last().dropna().pct_change().dropna()
    if len(d) < min_days or d.std() == 0:
        return float("nan")
    return float(d.mean() / d.std() * np.sqrt(365))


def equity_wide(equity: pd.DataFrame) -> pd.DataFrame:
    return equity.pivot(index="ts", columns="bot_id", values="equity").sort_index().ffill()


def bot_summary(bots: pd.DataFrame, trades: pd.DataFrame, equity: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, b in bots.iterrows():
        bid = b["bot_id"]
        e = equity[equity.bot_id == bid]
        t = trades[trades.bot_id == bid]
        sells = t[(t.side == "sell") & (t.kind != "funding")]          # cierres (el funding cobrado no es un cierre)
        wins, losses = sells[sells.realized_pnl > 0], sells[sells.realized_pnl < 0]
        gp = float(t.realized_pnl[t.realized_pnl > 0].sum())           # incluye funding, perpetuo y arbitraje
        gl = float(-t.realized_pnl[t.realized_pnl < 0].sum())
        last = e.iloc[-1] if len(e) else None
        eq_now = float(last.equity) if last is not None else float(b["capital"])
        rows.append({
            "bot_id": bid, "Bot": b["name"], "Estrategia": b["strategy"], "Estado": b["status"],
            "Detalle": b["status_detail"], "Plataforma": b["exchange"], "Monedas": b["symbols"],
            "Riesgo": b["risk_level"], "Capital": float(b["capital"]), "Equity": eq_now,
            "P&L": eq_now - float(b["capital"]),
            "ROI %": (eq_now / float(b["capital"]) - 1) * 100,
            "P&L realizado": float(last.realized_pnl) if last is not None else 0.0,
            "P&L no realizado": float(last.unrealized_pnl) if last is not None else 0.0,
            "Comisiones": float(last.fees_paid) if last is not None else 0.0,
            "Max DD %": max_drawdown(e.equity) * 100 if len(e) else 0.0,
            "Sharpe": sharpe_daily(e.equity, e.ts) if len(e) else float("nan"),
            "Operaciones": int(len(t)), "Cierres": int(len(sells)),
            "Win rate %": (len(wins) / len(sells) * 100) if len(sells) else float("nan"),
            "Ganancia bruta": gp, "Pérdida bruta": gl,
            "Profit factor": (gp / gl) if gl > 0 else (float("inf") if gp > 0 else float("nan")),
        })
    return pd.DataFrame(rows)


def overlap_report(bots: pd.DataFrame, equity: pd.DataFrame, resample: str = "4h",
                   corr_threshold: float = 0.6) -> tuple[pd.DataFrame, list[dict]]:
    """Correlación de retornos entre bots + monedas compartidas: señala solapamientos."""
    wide = equity_wide(equity)
    if wide.empty:
        return pd.DataFrame(), []
    wide.index = pd.to_datetime(wide.index, unit="ms", utc=True)
    rets = wide.resample(resample).last().pct_change().dropna(how="all")
    rets = rets.loc[:, rets.std() > 0]
    corr = rets.corr() if rets.shape[1] > 1 else pd.DataFrame()
    syms = {r.bot_id: set(r.symbols.split(",")) for r in bots.itertuples()}
    names = dict(zip(bots.bot_id, bots.name))
    flags = []
    ids = list(syms)
    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            x, y = ids[a], ids[b]
            shared = sorted(syms[x] & syms[y])
            c = float(corr.loc[x, y]) if (not corr.empty and x in corr.index and y in corr.columns) else float("nan")
            if shared or (not np.isnan(c) and c >= corr_threshold):
                flags.append({"Bots": f"{names[x]} ↔ {names[y]}", "Monedas compartidas": ", ".join(shared) or "—",
                              "Correlación": c, "Alerta": (not np.isnan(c) and c >= corr_threshold) or bool(shared)})
    return corr, flags


def format_report(data: dict) -> str:
    s = bot_summary(data["bots"], data["trades"], data["equity"])
    m = data["meta"]
    lines = [f"Fuente: {m.get('source', '?')} · modo: {m.get('mode', '?')} · capital ficticio por bot (USDT)", ""]
    if s.empty:
        return "\n".join(lines + ["Sin datos todavía."])
    show = s[["Bot", "Estado", "Capital", "Equity", "P&L", "ROI %", "Max DD %", "Operaciones", "Win rate %",
              "Profit factor", "Comisiones"]]
    lines.append(show.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
    tot_cap, tot_eq = s["Capital"].sum(), s["Equity"].sum()
    lines += ["", f"TOTAL asignado: {tot_cap:,.2f} -> {tot_eq:,.2f}  ({tot_eq - tot_cap:+,.2f} USDT, "
                  f"{(tot_eq / tot_cap - 1) * 100:+.2f}%)",
              f"Ganancia bruta histórica: {s['Ganancia bruta'].sum():,.2f} · Pérdida bruta histórica: {s['Pérdida bruta'].sum():,.2f}",
              "", "Resultado simulado con dinero ficticio. Resultados pasados no garantizan resultados futuros."]
    return "\n".join(lines)
