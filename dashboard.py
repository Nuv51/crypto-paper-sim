"""Dashboard del simulador (dinero ficticio, precios reales).   Ejecuta:  streamlit run dashboard.py

Lee la base SQLite que escribe `run.py` (modo solo lectura), así que puede estar abierto mientras
el modo live sigue simulando. Variable opcional: PAPER_DB (ruta de la base), DASH_TZ (zona horaria).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config
from sim import metrics
from sim.data import INTERVAL_MS
from sim.exchanges import EXCHANGES
from sim.forecast import DISCLAIMER, trend_forecast
from sim.ledger import read_only_connection

TZ = os.environ.get("DASH_TZ", "America/Monterrey")
DEFAULT_DB = os.environ.get("PAPER_DB", "data/paper.db")

# Paleta categórica validada (scripts/validate_palette.js): mismos 8 tonos, pasos distintos por modo.
LIGHT = dict(text="#0b0b0b", text2="#52514e", grid="rgba(82,81,78,0.18)", neutral="#f0efec",
             surface="#fcfcfb", blue="#2a78d6", red="#e34948",
             series=["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"])
DARK = dict(text="#f0efec", text2="#c3c2b7", grid="rgba(195,194,183,0.18)", neutral="#383835",
            surface="#1a1a19", blue="#3987e5", red="#e66767",
            series=["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"])

STATUS_LABEL = {"active": "Activo", "paused": "En pausa", "halted": "Detenido (revisión manual)"}
SIDE_LABEL = {"buy": "Compra", "sell": "Venta"}
KIND_LABEL = {"market": "Mercado", "limit": "Límite", "perp": "Perpetuo", "funding": "Funding", "arb": "Arbitraje"}


# ----------------------------------------------------------------------------------------- utilidades
def theme() -> dict:
    try:
        return DARK if st.context.theme.type == "dark" else LIGHT
    except Exception:
        return LIGHT


def local_time(ts_ms) -> pd.Series | pd.DatetimeIndex:
    t = pd.to_datetime(ts_ms, unit="ms", utc=True)
    return t.dt.tz_convert(TZ) if isinstance(t, pd.Series) else t.tz_convert(TZ)


def rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def bot_colors(bot_ids: list[str], T: dict) -> dict[str, str]:
    """El color sigue a la entidad (el bot), no a su posición en el ranking ni al filtro activo."""
    slot = {b["id"]: i for i, b in enumerate(config.BOTS)}
    nxt, out = len(slot), {}
    for bid in bot_ids:
        if bid not in slot:
            slot[bid], nxt = nxt, nxt + 1
        out[bid] = T["series"][slot[bid] % len(T["series"])]
    return out


def style(fig: go.Figure, T: dict, height: int = 380, hover: str = "x unified", yfmt: str | None = None,
          ysuffix: str = "") -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=40, b=10), hovermode=hover,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=T["text2"], size=12),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, font=dict(color=T["text2"])))
    fig.update_xaxes(showgrid=False, linecolor=T["grid"], tickfont=dict(color=T["text2"]))
    fig.update_yaxes(gridcolor=T["grid"], zeroline=True, zerolinecolor=T["grid"], tickformat=yfmt,
                     ticksuffix=ysuffix, tickfont=dict(color=T["text2"]))
    return fig


@st.cache_data(ttl=5, show_spinner=False)
def load(db_path: str, mtime: float) -> dict:
    con = read_only_connection(db_path)
    try:
        return metrics.load_all(con)
    finally:
        con.close()


def bot_params(row) -> dict:
    try:
        return json.loads(row["params"] or "{}")
    except Exception:
        return {}


# ----------------------------------------------------------------------------------------- contenido
def render(db_path: str) -> None:
    p = Path(db_path)
    if not p.exists():
        st.error(f"No encuentro la base `{db_path}`. Primero genera datos:  `python run.py replay --days 120`")
        st.stop()
    data = load(str(p), p.stat().st_mtime)
    T = theme()
    meta, bots, trades, equity, bars, events = (data[k] for k in ("meta", "bots", "trades", "equity", "bars", "events"))
    if bots.empty or equity.empty:
        st.info("La base existe pero todavía no tiene datos simulados.")
        st.stop()

    summary = metrics.bot_summary(bots, trades, equity)
    names = dict(zip(bots.bot_id, bots.name))
    colors = bot_colors(list(bots.bot_id), T)
    interval = meta.get("interval", "1h")
    bar_ms = INTERVAL_MS.get(interval, 3_600_000)

    # ---- encabezado: nunca dejar dudas de que es simulación
    source = meta.get("source", "?")
    t0, t1 = int(equity.ts.min()), int(equity.ts.max())
    span = f"{local_time(pd.Series([t0])).iloc[0]:%Y-%m-%d} → {local_time(pd.Series([t1])).iloc[0]:%Y-%m-%d %H:%M}"
    if "SINT" in source.upper():
        st.error(f"DATOS INVENTADOS ({source}). Esto solo prueba el código: no representa ningún mercado real.")
    else:
        st.warning(f"SIMULACIÓN con dinero ficticio · precios reales de {source} · modo {meta.get('mode', '?')} · {span}")

    wide = metrics.equity_wide(equity)
    cap = bots.set_index("bot_id")["capital"].astype(float)
    wide = wide[[c for c in wide.columns if c in cap.index]]
    total = wide.sum(axis=1)
    total_cap = float(cap[wide.columns].sum())
    pnl_total = float(total.iloc[-1]) - total_cap
    x_idx = local_time(wide.index)

    btc_ret = None
    b = bars[bars.symbol == "BTCUSDT"].drop_duplicates("ts").set_index("ts").close
    if not b.empty:
        b = b.reindex(wide.index).ffill().bfill()
        btc_ret = (b / b.iloc[0] - 1) * 100

    tabs = st.tabs(["Resumen", "P&L y operaciones", "Transacciones", "Riesgo y solapamiento",
                    "Tendencias (estimación)", "Ficha de bots"])

    # ====================================================================== Resumen
    with tabs[0]:
        c = st.columns(6)
        c[0].metric("Equity total (ficticio)", f"{total.iloc[-1]:,.2f} USDT")
        c[1].metric("P&L total", f"{pnl_total:+,.2f} USDT", f"{pnl_total / total_cap * 100:+.2f}%")
        c[2].metric("Ganancia histórica (all time)", f"{summary['Ganancia bruta'].sum():,.2f}")
        c[3].metric("Pérdida histórica (all time)", f"-{summary['Pérdida bruta'].sum():,.2f}")
        c[4].metric("Comisiones pagadas", f"{summary['Comisiones'].sum():,.2f}")
        c[5].metric("Max drawdown portafolio", f"{metrics.max_drawdown(total) * 100:.2f}%")
        st.caption("Ganancia/pérdida histórica = suma del P&L realizado de las ventas ganadoras / perdedoras, "
                   "neto de comisiones. No incluye P&L no realizado (posiciones abiertas). El capital mostrado es solo el "
                   "asignado a estos bots; el resto del portafolio queda como reserva.")
        if btc_ret is not None:
            port_ret = (total / total_cap - 1) * 100
            st.caption(f"Referencia: comprar y mantener BTC en el mismo periodo = {btc_ret.iloc[-1]:+.2f}% "
                       f"vs portafolio de bots = {port_ret.iloc[-1]:+.2f}% (el BTC de referencia sin comisiones).")

        st.markdown("**Rendimiento acumulado vs capital asignado (%)**")
        fig = go.Figure()
        for bid in wide.columns:
            fig.add_trace(go.Scatter(x=x_idx, y=(wide[bid] / cap[bid] - 1) * 100, mode="lines", name=names[bid],
                                     line=dict(color=colors[bid], width=2), hovertemplate="%{y:.2f}%"))
        fig.add_trace(go.Scatter(x=x_idx, y=(total / total_cap - 1) * 100, mode="lines", name="Portafolio de bots",
                                 line=dict(color=T["text"], width=3), hovertemplate="%{y:.2f}%"))
        if btc_ret is not None:
            fig.add_trace(go.Scatter(x=x_idx, y=btc_ret, mode="lines", name="BTC comprar y mantener",
                                     line=dict(color=T["text2"], width=2, dash="dot"), hovertemplate="%{y:.2f}%"))
        st.plotly_chart(style(fig, T, height=420, ysuffix="%"))

        st.markdown("**Estado y estrategia activa por bot**")
        view = summary.copy()
        view["Estado"] = view["Estado"].map(STATUS_LABEL).fillna(view["Estado"])
        view["Plataforma"] = view["Plataforma"].map(lambda k: EXCHANGES[k].name if k in EXCHANGES else k)
        view["Estrategia activa"] = view["Estrategia"] + " — " + view["Detalle"]
        cols = ["Bot", "Estado", "Estrategia activa", "Plataforma", "Monedas", "Riesgo", "Capital", "Equity", "P&L",
                "ROI %", "Max DD %", "Operaciones", "Win rate %", "Profit factor", "Sharpe"]
        st.dataframe(view[cols], hide_index=True, column_config={
            "Capital": st.column_config.NumberColumn(format="%.2f"), "Equity": st.column_config.NumberColumn(format="%.2f"),
            "P&L": st.column_config.NumberColumn(format="%.2f"), "ROI %": st.column_config.NumberColumn(format="%.2f"),
            "Max DD %": st.column_config.NumberColumn(format="%.2f"), "Win rate %": st.column_config.NumberColumn(format="%.1f"),
            "Profit factor": st.column_config.NumberColumn(format="%.2f"), "Sharpe": st.column_config.NumberColumn(format="%.2f")})
        halted = view[view["Estado"] != "Activo"]
        for _, r in halted.iterrows():
            reason = bots.loc[bots.bot_id == r["bot_id"], "status_reason"].iloc[0]
            st.info(f"{r['Bot']}: {r['Estado']}. {reason}")
        st.caption("Sharpe anualizado con retornos diarios; es NaN con menos de 20 días de datos. Con pocos datos "
                   "ninguna métrica es concluyente.")
        with st.expander("Ver datos de la gráfica (tabla)"):
            tbl = ((wide.div(cap[wide.columns]) - 1) * 100).round(3)
            tbl.index = x_idx
            tbl.columns = [names[c_] for c_ in tbl.columns]
            st.dataframe(tbl.iloc[::max(1, len(tbl) // 500)])

    # ====================================================================== P&L
    with tabs[1]:
        st.markdown("**P&L realizado acumulado por bot (USDT)**")
        rp = equity.pivot(index="ts", columns="bot_id", values="realized_pnl").sort_index().ffill()
        xr = local_time(rp.index)
        fig = go.Figure()
        for bid in rp.columns:
            fig.add_trace(go.Scatter(x=xr, y=rp[bid], mode="lines", name=names.get(bid, bid), line_shape="hv",
                                     line=dict(color=colors.get(bid), width=2), hovertemplate="%{y:,.2f}"))
        fig.add_trace(go.Scatter(x=xr, y=rp.sum(axis=1), mode="lines", name="Total", line_shape="hv",
                                 line=dict(color=T["text"], width=3), hovertemplate="%{y:,.2f}"))
        st.plotly_chart(style(fig, T, height=360))

        sells = trades[trades.side == "sell"].copy().reset_index(drop=True)
        st.markdown("**P&L por operación de cierre (USDT)**")
        if sells.empty:
            st.info("Todavía no hay ventas (cierres).")
        else:
            sells["n"] = np.arange(1, len(sells) + 1)
            sells["fecha"] = local_time(sells.ts).dt.strftime("%Y-%m-%d %H:%M")
            fig = go.Figure()
            for bid, g in sells.groupby("bot_id"):
                fig.add_trace(go.Bar(
                    x=g["n"], y=g["realized_pnl"], name=names.get(bid, bid), marker_color=colors.get(bid),
                    customdata=np.stack([g["fecha"], g["symbol"], g["reason"]], axis=-1),
                    hovertemplate="#%{x} · %{customdata[0]}<br>%{customdata[1]} · %{customdata[2]}<br>P&L %{y:,.2f}<extra>"
                                  + names.get(bid, bid) + "</extra>"))
            fig.update_layout(barmode="relative", bargap=0.15)
            st.plotly_chart(style(fig, T, height=340, hover="closest"))
            st.caption("El P&L de cada venta usa costo promedio ponderado e incluye comisiones de compra y venta. "
                       "En el grid, una venta puede salir negativa aunque el ciclo completo gane: el total acumulado sí es exacto.")

        st.markdown("**Ganadoras vs perdedoras por bot**")
        agg = summary[["Bot", "Cierres", "Ganancia bruta", "Pérdida bruta", "P&L realizado", "Win rate %", "Profit factor"]]
        st.dataframe(agg, hide_index=True)

    # ====================================================================== Transacciones
    with tabs[2]:
        f = trades.copy()
        if f.empty:
            st.info("Todavía no hay transacciones.")
        else:
            f["Fecha"] = local_time(f.ts).dt.strftime("%Y-%m-%d %H:%M")
            f["Bot"] = f.bot_id.map(names)
            f["Plataforma"] = f.exchange.map(lambda k: EXCHANGES[k].name if k in EXCHANGES else k)
            c1, c2, c3, c4 = st.columns(4)
            bsel = c1.multiselect("Bot", sorted(f["Bot"].unique()))
            psel = c2.multiselect("Plataforma", sorted(f["Plataforma"].unique()))
            msel = c3.multiselect("Criptomoneda", sorted(f.symbol.unique()))
            tsel = c4.multiselect("Tipo", ["Compra", "Venta"])
            if bsel:
                f = f[f["Bot"].isin(bsel)]
            if psel:
                f = f[f["Plataforma"].isin(psel)]
            if msel:
                f = f[f.symbol.isin(msel)]
            if tsel:
                f = f[f.side.map(SIDE_LABEL).isin(tsel)]
            out = pd.DataFrame({
                "Fecha": f["Fecha"], "Bot": f["Bot"], "Plataforma": f["Plataforma"], "Moneda": f.symbol,
                "Tipo": f.side.map(SIDE_LABEL), "Orden": f.kind.map(KIND_LABEL), "Cantidad": f.qty,
                "Precio": f.price, "Monto USDT": f.notional, "Comisión": f.fee,
                "P&L": f.realized_pnl.where(f.side == "sell"), "Motivo": f.reason})
            st.caption(f"{len(out):,} transacciones")
            st.dataframe(out.iloc[::-1], hide_index=True, column_config={
                "Cantidad": st.column_config.NumberColumn(format="%.6f"), "Precio": st.column_config.NumberColumn(format="%.4f"),
                "Monto USDT": st.column_config.NumberColumn(format="%.2f"), "Comisión": st.column_config.NumberColumn(format="%.3f"),
                "P&L": st.column_config.NumberColumn(format="%.2f")})

            sym = st.selectbox("Ver operaciones sobre el precio de", sorted(trades.symbol.unique()))
            pb = bars[bars.symbol == sym].drop_duplicates("ts")
            tt = trades[trades.symbol == sym]
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=local_time(pb.ts), y=pb.close, mode="lines", name=f"{sym} cierre",
                                     line=dict(color=T["text2"], width=1.5), hovertemplate="%{y:,.4f}"))
            for side, symbol_, fill in (("buy", "triangle-up", T["text"]), ("sell", "triangle-down", T["surface"])):
                g = tt[tt.side == side]
                fig.add_trace(go.Scatter(
                    x=local_time(g.ts), y=g.price, mode="markers", name=SIDE_LABEL[side],
                    marker=dict(symbol=symbol_, size=10, color=fill, line=dict(color=T["text"], width=2)),
                    customdata=np.stack([g.bot_id.map(names), g.reason], axis=-1) if len(g) else None,
                    hovertemplate="%{customdata[0]} · %{customdata[1]}<br>%{y:,.4f}<extra>" + SIDE_LABEL[side] + "</extra>"))
            st.plotly_chart(style(fig, T, height=380, hover="closest"))
            st.caption("Triángulo lleno = compra · triángulo vacío = venta (la forma, no el color, distingue el tipo).")

    # ====================================================================== Riesgo y solapamiento
    with tabs[3]:
        st.markdown("**Drawdown de cada bot desde su máximo de equity (%)**")
        fig = go.Figure()
        for bid in wide.columns:
            dd = (wide[bid] / wide[bid].cummax() - 1) * 100
            fig.add_trace(go.Scatter(x=x_idx, y=dd, mode="lines", name=names[bid],
                                     line=dict(color=colors[bid], width=2), hovertemplate="%{y:.2f}%"))
        st.plotly_chart(style(fig, T, height=340, ysuffix="%"))
        lim = []
        for _, r in bots.iterrows():
            rk = bot_params(r).get("_risk", {})
            lim.append({"Bot": r["name"], "Límite de drawdown": f"{rk.get('max_drawdown', 0) * 100:.0f}%" if rk.get("max_drawdown") else "—",
                        "Acción al romperlo": {"liquidate_and_halt": "Liquidar y detener (revisión manual)",
                                               "pause_and_resume": f"Liquidar y pausar {rk.get('cooldown_bars', '?')} barras",
                                               "flag_only": "Solo alerta de revisión manual"}.get(rk.get("action"), "—")})
        st.dataframe(pd.DataFrame(lim), hide_index=True)

        st.markdown("**Solapamiento entre bots**")
        corr, flags = metrics.overlap_report(bots, equity)
        if not corr.empty:
            lab = [names[i] for i in corr.index]
            fig = go.Figure(go.Heatmap(
                z=corr.values, x=lab, y=lab, zmin=-1, zmax=1,
                colorscale=[[0, T["blue"]], [0.5, T["neutral"]], [1, T["red"]]],
                text=np.round(corr.values, 2), texttemplate="%{text}", colorbar=dict(title="correlación"),
                hovertemplate="%{y} ↔ %{x}: %{z:.2f}<extra></extra>"))
            fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10), paper_bgcolor="rgba(0,0,0,0)",
                              plot_bgcolor="rgba(0,0,0,0)", font=dict(color=T["text2"], size=12))
            st.plotly_chart(fig)
            st.caption("Correlación de retornos de cada 4 horas entre bots (azul = se mueven en sentidos opuestos, "
                       "rojo = juntos). Bots muy correlacionados no diversifican: son casi el mismo bot.")
        else:
            st.caption("Aún no hay suficientes datos para calcular correlaciones (o hay un solo bot con variación).")
        if flags:
            fl = pd.DataFrame(flags)
            fl["Alerta"] = fl["Alerta"].map({True: "Revisar", False: "—"})
            st.dataframe(fl, hide_index=True, column_config={"Correlación": st.column_config.NumberColumn(format="%.2f")})
        else:
            st.success("No se detectan solapamientos por monedas ni correlación alta.")

        st.markdown("**Eventos y alertas recientes**")
        ev = events.copy()
        if ev.empty:
            st.caption("Sin eventos.")
        else:
            ev["Fecha"] = local_time(ev.ts).dt.strftime("%Y-%m-%d %H:%M")
            ev["Bot"] = ev.bot_id.map(names).fillna("—")
            ev["Nivel"] = ev.level.map({"alert": "ALERTA", "warn": "Aviso", "info": "Info"}).fillna(ev.level)
            st.dataframe(ev[["Fecha", "Bot", "Nivel", "message"]].rename(columns={"message": "Mensaje"}).head(100),
                         hide_index=True)

    # ====================================================================== Tendencias
    with tabs[4]:
        st.warning(DISCLAIMER)
        syms = sorted(s_ for s_ in bars.symbol.unique() if "~" not in s_)    # las fuentes "~" no son un mercado para graficar
        c1, c2, c3 = st.columns(3)
        sym = c1.selectbox("Moneda", syms)
        horizon = c2.selectbox("Horizonte (barras)", [12, 24, 48, 72], index=1)
        lookback = c3.selectbox("Ventana de ajuste (barras)", [72, 168, 336], index=1)
        per_day = 86_400_000 / bar_ms

        rows = []
        for s_ in syms:
            cl = bars[bars.symbol == s_].drop_duplicates("ts").set_index("ts").close
            r = trend_forecast(cl, lookback, horizon)
            if r:
                rows.append({"Moneda": s_, "Tendencia estimada": r["direction"], "t-stat": r["t_stat"],
                             "Pendiente %/día": r["slope_pct_per_bar"] * per_day * 100,
                             "Precio actual": r["last_price"], "Rango ±2σ al horizonte": f"{r['end_lo2']:,.4f} – {r['end_hi2']:,.4f}"})
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, column_config={
                "t-stat": st.column_config.NumberColumn(format="%.1f"),
                "Pendiente %/día": st.column_config.NumberColumn(format="%.2f"),
                "Precio actual": st.column_config.NumberColumn(format="%.4f")})

        cl = bars[bars.symbol == sym].drop_duplicates("ts").set_index("ts").close
        fc = trend_forecast(cl, lookback, horizon)
        if fc is None:
            st.info("Faltan datos para estimar.")
        else:
            hist = cl.tail(lookback * 2)
            fx = local_time(pd.Series(int(cl.index[-1]) + fc["steps"] * bar_ms))
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=local_time(pd.Series(hist.index)), y=hist.values, mode="lines",
                                     name="Precio (cierre)", line=dict(color=T["text2"], width=2), hovertemplate="%{y:,.4f}"))
            fig.add_trace(go.Scatter(x=fx, y=fc["hi2"], mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"))
            fig.add_trace(go.Scatter(x=fx, y=fc["lo2"], mode="lines", line=dict(width=0), fill="tonexty",
                                     fillcolor=rgba(T["blue"], 0.12), name="Rango ±2σ", hoverinfo="skip"))
            fig.add_trace(go.Scatter(x=fx, y=fc["hi1"], mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"))
            fig.add_trace(go.Scatter(x=fx, y=fc["lo1"], mode="lines", line=dict(width=0), fill="tonexty",
                                     fillcolor=rgba(T["blue"], 0.25), name="Rango ±1σ", hoverinfo="skip"))
            fig.add_trace(go.Scatter(x=fx, y=fc["center"], mode="lines", name="Tendencia estimada",
                                     line=dict(color=T["blue"], width=2, dash="dash"), hovertemplate="%{y:,.4f}"))
            st.plotly_chart(style(fig, T, height=400))
            st.caption(f"{sym}: tendencia {fc['direction']} (t-stat {fc['t_stat']:.1f}). Al horizonte, el modelo centra el precio en "
                       f"{fc['end_center']:,.4f} con rango ±2σ de {fc['end_lo2']:,.4f} a {fc['end_hi2']:,.4f}. "
                       "Fíjate en que el cono suele ser mucho más ancho que el movimiento estimado: la 'tendencia' rara vez supera el ruido.")

    # ====================================================================== Ficha de bots
    with tabs[5]:
        st.markdown("**Documentación de cada bot** (qué opera, cómo, dónde y en qué se diferencia)")
        rows = []
        for _, r in bots.iterrows():
            ex = EXCHANGES.get(r["exchange"])
            rows.append({"Bot": r["name"], "Monedas": r["symbols"].replace("USDT", ""), "Estrategia": r["strategy"],
                         "Plataforma": ex.name if ex else r["exchange"],
                         "Comisión maker/taker": f"{ex.maker * 100:.3f}% / {ex.taker * 100:.3f}%" if ex else "—",
                         "Perfil de volatilidad": r["vol_profile"], "Riesgo": r["risk_level"],
                         "Capital (USDT)": r["capital"], "En qué se diferencia": r["differentiator"]})
        st.dataframe(pd.DataFrame(rows), hide_index=True)
        with st.expander("Parámetros de cada bot"):
            for _, r in bots.iterrows():
                st.markdown(f"**{r['name']}**")
                st.json(bot_params(r))


# ----------------------------------------------------------------------------------------- app
st.set_page_config(page_title="Simulador de bots cripto", layout="wide")
st.title("Simulador de bots cripto — dinero ficticio")

db = st.sidebar.text_input("Base de datos", DEFAULT_DB)
auto = st.sidebar.toggle("Auto-actualizar cada 30 s (modo live)", value=False)
st.sidebar.caption("Resultados simulados; los resultados pasados no garantizan resultados futuros.")

if auto:
    st.fragment(run_every=30)(render)(db)
else:
    render(db)
