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


# Familias de estrategia para la pestaña Summary. Se deducen del tipo de bot (sufijo del id, p.ej. "b04_grid" -> "grid")
# y viven aquí, no en config.py: así agrupar de otra forma no cambia la huella de configuración ni reinicia la simulación.
FAMILIES = [
    ("neutral", "Neutral al mercado", ("carry", "stable", "xrp"),
     "Ganan por funding, desvío del peg o diferencia de precio entre plataformas, no por la dirección del mercado."),
    ("rango", "Rango y reversión", ("grid", "meanrev", "mm"),
     "Ganan si el precio oscila: venden caro y compran barato dentro de un rango. Sufren cuando hay tendencia fuerte."),
    ("tendencia", "Tendencia y señales", ("trend", "breakout", "ml"),
     "Ganan si el precio sigue una dirección. Compran fuerza o siguen una señal; pierden en mercados laterales."),
    ("acumulacion", "Acumulación", ("dca",),
     "Compra periódica de monto fijo, sin señales ni stop. Es acumulación, no una ventaja estadística."),
    ("indice", "Índice pasivo", ("index",),
     "Compran el mercado (Top-25/Top-50) y rebalancean periódicamente. Sin señales: sirven de vara para medir si los bots activos pagan su complejidad."),
    ("efectivo", "Efectivo", ("cash",),
     "Reserva sin invertir: no opera ni rinde. Se incluye para que el ROI cuente el capital completo."),
]


def family_of(bot_id: str) -> str:
    kind = str(bot_id).split("_", 1)[-1].split("_")[0]          # "b11_grid_btc" -> "grid": varios bots del mismo tipo
    for key, _name, kinds, _desc in FAMILIES:
        if kind in kinds:
            return key
    return "otros"


def _last_prices(bars: pd.DataFrame) -> dict:
    """Último cierre por símbolo de mercado (los símbolos con '~' son fuentes especiales, no se valúan)."""
    px = {}
    if bars is None or bars.empty:
        return px
    last = bars.sort_values("ts").groupby("symbol").close.last()
    for sym, v in last.items():
        if "~" not in sym and math.isfinite(float(v)):
            px[sym] = float(v)
    return px


def _bot_positions(bot_state: pd.DataFrame, px: dict) -> tuple[dict, dict]:
    """Posiciones spot largas por bot (cantidad y valor al último cierre) y valor cubierto con cortos de perpetuo."""
    pos, hedged = {}, {}
    if bot_state is None or bot_state.empty:
        return pos, hedged
    for _, r in bot_state.iterrows():
        try:
            st = json.loads(r["state"] or "{}")
        except Exception:
            continue
        rows = []
        for sym, qa in (st.get("wallet", {}).get("positions") or {}).items():
            qty = float(qa[0])
            if qty > 1e-12 and sym in px:
                rows.append({"symbol": sym, "qty": qty, "value": qty * px[sym]})
        pos[r["bot_id"]] = rows
        perp = float((st.get("strategy") or {}).get("perp_qty") or 0.0)
        if perp > 0:                                   # carry: corto en el perpetuo de la misma moneda
            hedged[r["bot_id"]] = perp
    return pos, hedged


def _risk_proximity(b: dict, st: dict, last_ts: int, bar_ms: int) -> dict:
    """Qué tan cerca está un bot de su límite de drawdown, medido igual que el control de riesgo del motor
    (caída del equity actual contra su máximo vigente, que se reinicia al reanudar tras una pausa)."""
    rk = b.get("risk") or {}
    limit = rk.get("max_drawdown")
    peak = float(st.get("peak") or 0.0)
    eq = b["equity"]
    status = b["status"]
    dd = max(0.0, 1 - float(eq) / peak) if (peak > 0 and eq is not None) else 0.0
    used = dd / limit if limit else None
    warn_at = float(rk.get("warn_at", 0.8))
    if status != "active":
        level = status                                   # paused | retired | halted
    elif used is None:
        level = "ok"
    elif used >= warn_at:
        level = "near"
    elif used >= 0.5:
        level = "watch"
    else:
        level = "ok"
    window = int(rk.get("strike_window_bars", 720)) * bar_ms
    strikes = [t for t in (st.get("strikes") or []) if last_ts - t < window]
    return {"limit": limit, "action": rk.get("action", "liquidate_and_halt"), "dd": dd, "used": used,
            "level": level, "peak": peak, "warn_at": warn_at, "strikes": len(strikes),
            "max_strikes": rk.get("max_strikes"), "pause_until": st.get("pause_until") if status == "paused" else None,
            "flagged": bool(st.get("flagged"))}


def _sim_info(meta: dict, interval: str) -> dict:
    """Qué simulación es (id, nombre, descripción) para que cada tablero se identifique y pueda compararse con el otro."""
    try:
        info = json.loads(meta.get("sim") or "null") or {}
    except Exception:
        info = {}
    return {"id": info.get("id", "actual"), "name": info.get("name", "Simulador actual"),
            "desc": info.get("desc", ""), "other": info.get("other"), "interval": interval}


def _sample_idx(n: int, max_points: int) -> np.ndarray:
    if n <= max_points:
        return np.arange(n)
    idx = np.unique(np.linspace(0, n - 1, max_points).round().astype(int))
    return idx


def build_dashboard(data: dict, now_ms: int, max_points: int = 1500, price_bars: int = 336,
                    trade_limit: int = 2000, event_limit: int = 80, benchmarks: dict | None = None,
                    fear_greed: dict | None = None) -> dict:
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

    # ---- posiciones por activo y familias de estrategia (pestaña Summary)
    px = _last_prices(bars)
    pos, perp_qty = _bot_positions(data.get("bot_state"), px)
    by_asset, hedged = {}, {}
    for b in bot_rows:
        b["family"] = family_of(b["id"])
        b["positions"] = [dict(p) for p in pos.get(b["id"], [])]
        invested = sum(p["value"] for p in b["positions"])
        b["cash"] = None if b["equity"] is None else float(b["equity"]) - invested
        for p in b["positions"]:
            a = by_asset.setdefault(p["symbol"], {"symbol": p["symbol"], "value": 0.0, "bots": []})
            a["value"] += p["value"]
            a["bots"].append(b["id"])
        for s in b["symbols"]:
            if s.endswith("~PERP") and b["id"] in perp_qty and s.split("~")[0] in px:
                base = s.split("~")[0]
                hedged[base] = hedged.get(base, 0.0) + perp_qty[b["id"]] * px[base]
    eq_total = sum(float(b["equity"]) for b in bot_rows if b["equity"] is not None)
    invested_total = sum(a["value"] for a in by_asset.values())
    holdings = {"total": eq_total, "invested": invested_total, "cash": eq_total - invested_total,
                "hedged": sum(hedged.values()),
                "by_asset": sorted(by_asset.values(), key=lambda a: -a["value"])}
    families = []
    for key, name, _kinds, desc in FAMILIES + [("otros", "Otros", (), "Bots sin clasificar.")]:
        members = [b for b in bot_rows if b["family"] == key]
        if not members:
            continue
        capital = sum(b["capital"] for b in members)
        fam_eq = sum(float(b["equity"]) for b in members if b["equity"] is not None)
        families.append({"key": key, "name": name, "desc": desc, "bots": [b["id"] for b in members], "capital": capital,
                         "equity": fam_eq, "pnl": fam_eq - capital, "roi": (fam_eq / capital - 1) * 100 if capital else None,
                         "n_trades": sum(b["n_trades"] or 0 for b in members)})

    # ---- cercanía al límite de riesgo (por bot y del portafolio entero)
    states = {}
    bs = data.get("bot_state")
    if bs is not None and not bs.empty:
        for _, r in bs.iterrows():
            try:
                states[r["bot_id"]] = json.loads(r["state"] or "{}")
            except Exception:
                states[r["bot_id"]] = {}
    last_ts = int(wide.index[-1])
    for b in bot_rows:
        b["risk_now"] = _risk_proximity(b, states.get(b["id"], {}), last_ts, bar_ms)
    portfolio_risk = None
    try:
        g = json.loads(meta.get("portfolio_risk") or "null")
    except Exception:
        g = None
    if g and g.get("limit"):
        peak = float(g["peak"])
        dd = max(0.0, 1 - float(total.iloc[-1]) / peak) if peak > 0 else 0.0
        portfolio_risk = {"limit": g["limit"], "dd": dd, "used": dd / g["limit"], "peak": peak, "status": g["status"],
                          "until": g["until"] if g["status"] == "paused" else None, "trips": g["trips"],
                          "cooldown_bars": g.get("cooldown_bars"), "bar_ms": bar_ms}

    # ---- atribución: cuánto del resultado lo puso el mercado y cuánto los propios bots
    attrib = data.get("attrib")
    mkt_cum = own_cum = None
    if attrib is not None and not attrib.empty:
        mk = attrib.pivot_table(index="ts", columns="bot_id", values="market", aggfunc="sum").reindex(wide.index).fillna(0.0)
        mk = mk[[c for c in mk.columns if c in wide.columns]].reindex(columns=wide.columns, fill_value=0.0)
        mk_cum = mk.cumsum()
        mkt_cum = mk_cum.sum(axis=1)
        own_cum = (total - total_cap) - mkt_cum
        for b in bot_rows:
            if b["id"] in mk_cum.columns and b["pnl"] is not None:
                b["market"] = float(mk_cum[b["id"]].iloc[-1])
                b["own"] = float(b["pnl"]) - b["market"]

    # ---- KPIs
    port_ret =(float(total.iloc[-1]) / total_cap - 1) * 100
    kpis = {
        "equity": float(total.iloc[-1]), "capital": total_cap, "pnl": float(total.iloc[-1]) - total_cap,
        "roi": port_ret, "gross_profit": float(summary["Ganancia bruta"].sum()),
        "gross_loss": float(summary["Pérdida bruta"].sum()), "fees": float(summary["Comisiones"].sum()),
        "max_dd": metrics.max_drawdown(total) * 100,
        "btc_ret": None if btc is None else float((btc.iloc[-1] / btc.iloc[0] - 1) * 100),
        "first_ts": int(wide.index[0]), "last_ts": int(wide.index[-1]), "n_trades": int(len(trades)),
        "reserve": None,
    }
    # máximo y mínimo históricos del equity del portafolio (sobre TODAS las velas, no sobre la serie muestreada del tablero)
    _tv = total.to_numpy(dtype=float)
    if len(_tv):
        _hi, _lo = int(np.argmax(_tv)), int(np.argmin(_tv))
        kpis.update(equity_high=float(_tv[_hi]), equity_high_ts=int(total.index[_hi]), equity_low=float(_tv[_lo]), equity_low_ts=int(total.index[_lo]))
    if mkt_cum is not None:
        kpis["market_pnl"], kpis["own_pnl"] = float(mkt_cum.iloc[-1]), float(own_cum.iloc[-1])
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
    fam_series = {}
    for key, name, _kinds, _desc in FAMILIES + [("otros", "Otros", (), "")]:
        members = [c for c in wide.columns if family_of(c) == key]
        if not members:
            continue
        fe = wide[members].sum(axis=1)
        fcap = float(cap[members].sum())
        fam_series[key] = {"capital": fcap, "equity": fe.to_numpy()[idx].round(4),
                           "realized": realized[[c for c in members if c in realized.columns]].sum(axis=1).to_numpy()[idx].round(4),
                           "drawdown": ((fe / fe.cummax() - 1) * 100).to_numpy()[idx].round(4)}
    series["family"] = fam_series
    if mkt_cum is not None:                   # acumulados desde el inicio; la página los resta entre dos fechas
        series["market_cum"] = mkt_cum.to_numpy()[idx].round(4)
        series["own_cum"] = own_cum.to_numpy()[idx].round(4)

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
        if "~" in sym:                       # fuentes especiales (perpetuo, foto XRP): no son un mercado para graficar
            continue
        g = g.drop_duplicates("ts").sort_values("ts")
        cl = g.set_index("ts").close
        tail = g.tail(min(700, int(round(price_bars * 3_600_000 / bar_ms))))      # ~14 días de velas de 1 h; con velas cortas, tope de 700
        prices[sym] = {"ts": tail.ts.to_numpy(), "close": tail.close.round(8).to_numpy()}
        hs, base = {}, None
        bars_per_h = 3_600_000 / bar_ms
        look = max(30, int(round(168 * bars_per_h)))          # siempre ~7 días de historia, sea cual sea el tamaño de la vela
        for hrs in (24, 72):                                  # horizontes en HORAS (las claves "24"/"72" son horas)
            H = max(1, int(round(hrs * bars_per_h)))
            r = trend_forecast(cl, look, H)
            if r:
                base = base or r
                hs[str(hrs)] = {k: np.round(r[k], 8) for k in ("center", "lo1", "hi1", "lo2", "hi2")}
                hs[str(hrs)].update(end_center=r["end_center"], end_lo2=r["end_lo2"], end_hi2=r["end_hi2"])
        if base:
            forecasts[sym] = {"direction": base["direction"], "t_stat": base["t_stat"],
                              "slope_pct_day": base["slope_pct_per_bar"] * per_day * 100,
                              "last_price": base["last_price"], "h": hs}

    out = {
        "generated_at": now_ms, "bar_ms": bar_ms, "interval": interval,
        "source": meta.get("source", "?"), "mode": meta.get("mode", "?"),
        "synthetic": "SINT" in meta.get("source", "").upper(),
        "sim": _sim_info(meta, interval),
        "disclaimer": DISCLAIMER, "kpis": kpis, "portfolio_risk": portfolio_risk, "bots": bot_rows, "holdings": holdings, "families": families, "series": series,
        "trades": {"cols": tcols, "rows": t_out.to_numpy(dtype=object).tolist(), "total": int(len(trades))},
        "events": ev[["ts", "bot_id", "level", "message"]].to_numpy(dtype=object).tolist(),
        "overlap": overlap, "prices": prices, "forecasts": forecasts,
    }
    if benchmarks:                       # historia de BTC, ETH y del índice de mercado para periodos largos (opcional)
        out["benchmarks"] = benchmarks
    if fear_greed:                       # sentimiento general del mercado cripto (opcional, fuente externa)
        out["fear_greed"] = fear_greed
    return _j(out)
