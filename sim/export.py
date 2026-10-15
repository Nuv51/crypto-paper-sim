"""Exporta todo lo que necesita el dashboard web a un único dashboard.json (ya calculado en Python:
métricas, correlaciones y estimaciones de tendencia). La página solo dibuja; no recalcula nada.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

from . import metrics
from .data import INTERVAL_MS
from .exchanges import EXCHANGES
from .forecast import DISCLAIMER, trend_forecast


def _j(x):
    """Convierte numpy/NaN/inf a valores JSON válidos (NaN -> null)."""
    if isinstance(x, (np.floating, float)):
        x = float(x)
        return x if math.isfinite(x) else None
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.ndarray):
        return [_j(v) for v in x.tolist()]
    if isinstance(x, dict):
        return {k: _j(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_j(v) for v in x]
    return x


def _sample_idx(n: int, max_points: int) -> np.ndarray:
    if n <= max_points:
        return np.arange(n)
    idx = np.unique(np.linspace(0, n - 1, max_points).round().astype(int))
    return idx


def build_dashboard(data: dict, now_ms: int, max_points: int = 1500, price_bars: int = 336,
                    trade_limit: int = 2000, event_limit: int = 80) -> dict:
    meta, bots, trades, equity, bars, events = (data[k] for k in ("meta", "bots", "trades", "equity", "bars", "events"))
    interval = meta.get("interval", "1h")
    bar_ms = INTERVAL_MS.get(interval, 3_600_000)
    summary = metrics.bot_summary(bots, trades, equity).set_index("bot_id")

    wide = metrics.equity_wide(equity)
    cap = bots.set_index("bot_id")["capital"].astype(float)
    wide = wide[[c for c in wide.columns if c in cap.index]]
    total = wide.sum(axis=1)
    total_cap = float(cap[wide.columns].sum())
    idx = _sample_idx(len(wide), max_points)
    ts_s = wide.index.to_numpy()[idx]

    realized = equity.pivot(index="ts", columns="bot_id", values="realized_pnl").sort_index().ffill().reindex(wide.index).ffill()
    dd_full = (wide / wide.cummax() - 1) * 100
    dd_total = (total / total.cummax() - 1) * 100

    btc = None
    b = bars[bars.symbol == "BTCUSDT"].drop_duplicates("ts").set_index("ts").close
    if not b.empty:
        btc = b.reindex(wide.index).ffill().bfill()

    # ---- bots
    bot_rows = []
    for _, r in bots.iterrows():
        bid = r["bot_id"]
        s = summary.loc[bid] if bid in summary.index else None
        ex = EXCHANGES.get(r["exchange"])
        try:
            params = json.loads(r["params"] or "{}")
        except Exception:
            params = {}
        bot_rows.append({
            "id": bid, "name": r["name"], "strategy": r["strategy"], "exchange": r["exchange"],
            "exchange_name": ex.name if ex else r["exchange"],
            "maker": ex.maker if ex else None, "taker": ex.taker if ex else None,
            "symbols": r["symbols"].split(","), "vol_profile": r["vol_profile"], "risk_level": r["risk_level"],
            "capital": float(r["capital"]), "differentiator": r["differentiator"],
            "status": r["status"], "status_reason": r["status_reason"], "status_detail": r["status_detail"],
            "risk": params.get("_risk", {}), "params": {k: v for k, v in params.items() if not k.startswith("_")},
            "equity": None if s is None else s["Equity"], "pnl": None if s is None else s["P&L"],
            "roi": None if s is None else s["ROI %"], "realized": None if s is None else s["P&L realizado"],
            "unrealized": None if s is None else s["P&L no realizado"], "fees": None if s is None else s["Comisiones"],
            "max_dd": None if s is None else s["Max DD %"], "sharpe": None if s is None else s["Sharpe"],
            "n_trades": None if s is None else int(s["Operaciones"]), "n_closes": None if s is None else int(s["Cierres"]),
            "win_rate": None if s is None else s["Win rate %"],
            "gross_profit": None if s is None else s["Ganancia bruta"], "gross_loss": None if s is None else s["Pérdida bruta"],
            "profit_factor": None if s is None else s["Profit factor"],
        })

    # ---- KPIs
    port_ret = (float(total.iloc[-1]) / total_cap - 1) * 100
    kpis = {
        "equity": float(total.iloc[-1]), "capital": total_cap, "pnl": float(total.iloc[-1]) - total_cap,
        "roi": port_ret, "gross_profit": float(summary["Ganancia bruta"].sum()),
        "gross_loss": float(summary["Pérdida bruta"].sum()), "fees": float(summary["Comisiones"].sum()),
        "max_dd": metrics.max_drawdown(total) * 100,
        "btc_ret": None if btc is None else float((btc.iloc[-1] / btc.iloc[0] - 1) * 100),
        "first_ts": int(wide.index[0]), "last_ts": int(wide.index[-1]), "n_trades": int(len(trades)),
        "reserve": None,
    }
    pc = meta.get("portfolio_capital")
    if pc:
        kpis["reserve"] = float(pc) - total_cap

    # ---- series
    series = {
        "ts": ts_s,
        "equity": {c: wide[c].to_numpy()[idx].round(4) for c in wide.columns},
        "total": total.to_numpy()[idx].round(4),
        "btc": None if btc is None else btc.to_numpy()[idx].round(6),
        "realized": {c: realized[c].to_numpy()[idx].round(4) for c in realized.columns if c in wide.columns},
        "drawdown": {c: dd_full[c].to_numpy()[idx].round(4) for c in wide.columns},
        "drawdown_total": dd_total.to_numpy()[idx].round(4),
    }

    # ---- operaciones y eventos
    tcols = ["ts", "bot_id", "exchange", "symbol", "side", "kind", "qty", "price", "notional", "fee", "realized_pnl", "reason"]
    t_out = trades[tcols].tail(trade_limit)
    ev = events.head(event_limit)

    # ---- solapamiento
    corr, flags = metrics.overlap_report(bots, equity)
    names = dict(zip(bots.bot_id, bots.name))
    overlap = {"labels": [names[i] for i in corr.index] if not corr.empty else [],
               "matrix": corr.values.round(4).tolist() if not corr.empty else [],
               "flags": [{"bots": f["Bots"], "shared": f["Monedas compartidas"], "corr": f["Correlación"], "alert": bool(f["Alerta"])} for f in flags]}

    # ---- precios y estimaciones de tendencia
    per_day = 86_400_000 / bar_ms
    prices, forecasts = {}, {}
    for sym, g in bars.groupby("symbol"):
        g = g.drop_duplicates("ts").sort_values("ts")
        cl = g.set_index("ts").close
        tail = g.tail(price_bars)
        prices[sym] = {"ts": tail.ts.to_numpy(), "close": tail.close.round(8).to_numpy()}
        hs, base = {}, None
        for H in (24, 72):
            r = trend_forecast(cl, 168, H)
            if r:
                base = base or r
                hs[str(H)] = {k: np.round(r[k], 8) for k in ("center", "lo1", "hi1", "lo2", "hi2")}
                hs[str(H)].update(end_center=r["end_center"], end_lo2=r["end_lo2"], end_hi2=r["end_hi2"])
        if base:
            forecasts[sym] = {"direction": base["direction"], "t_stat": base["t_stat"],
                              "slope_pct_day": base["slope_pct_per_bar"] * per_day * 100,
                              "last_price": base["last_price"], "h": hs}

    out = {
        "generated_at": now_ms, "bar_ms": bar_ms, "interval": interval,
        "source": meta.get("source", "?"), "mode": meta.get("mode", "?"),
        "synthetic": "SINT" in meta.get("source", "").upper(),
        "disclaimer": DISCLAIMER, "kpis": kpis, "bots": bot_rows, "series": series,
        "trades": {"cols": tcols, "rows": t_out.to_numpy(dtype=object).tolist(), "total": int(len(trades))},
        "events": ev[["ts", "bot_id", "level", "message"]].to_numpy(dtype=object).tolist(),
        "overlap": overlap, "prices": prices, "forecasts": forecasts,
    }
    return _j(out)
