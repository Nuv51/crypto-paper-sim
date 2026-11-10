"""Observatorio de mercado · FASE 0: ¿dónde está el precio dentro de su rango de 12 meses, y eso anticipa algo?

Solo mide (no opera). Las definiciones, los horizontes y los criterios están fijados en OBSERVATORIO_MERCADO.md (pre-registro)
ANTES de calcular nada; este módulo los implementa tal cual.

  · coin_features(close)   -> etiquetas por moneda + descriptivas (percentil, distancias, caída desde el máximo…)
  · build_panel(closes)    -> matriz (monedas × días) con todas las etiquetas, incluidas las de mercado (amplitud)
  · evaluate(...)          -> qué hizo el precio después (7/30/90 días) frente a su línea base, por episodios, con prueba
                              de permutación por DESPLAZAMIENTO CIRCULAR (conserva cómo se agrupan las monedas y los episodios)
  · run_phase0(closes)     -> resultados completos + veredicto por etiqueta y horizonte + alertas del día

Un episodio es un grupo de días con la etiqueta separados por menos de 30 días (cuenta su primer día). Un episodio de mercado
agrupa episodios de cualquier moneda a menos de 30 días. Es el recuento que importa: las monedas caen casi todas el mismo día.

Sesgo de supervivencia: el universo se eligió hoy; los rebotes tras mínimos se ven mejor de lo que fueron.
Nada de esto es una señal de compra o venta ni una garantía.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

WINDOW = 365                       # días de la ventana (sin contar el día evaluado: 364 previos para mínimos/máximos)
GAP = 30                           # días: eventos separados por menos de esto forman un mismo episodio
HORIZONS = (7, 30, 90)             # días hacia adelante
COIN_LABELS = ("min12m", "max12m", "peor_semana", "mejor_semana", "vol_baja", "vol_alta")
MARKET_LABELS = ("capitulacion_amplia", "euforia_amplia")
ALL_LABELS = COIN_LABELS + MARKET_LABELS
LABEL_TEXT = {
    "min12m": "Mínimo de 12 meses", "max12m": "Máximo de 12 meses",
    "peor_semana": "Peor semana del año", "mejor_semana": "Mejor semana del año",
    "vol_baja": "Volatilidad inusualmente baja", "vol_alta": "Volatilidad inusualmente alta",
    "capitulacion_amplia": "Capitulación amplia (muchas monedas en mínimos)",
    "euforia_amplia": "Euforia amplia (muchas monedas en máximos)",
}
VOL_PCT_LOW, VOL_PCT_HIGH = 0.10, 0.90
BREADTH_SHARE, BREADTH_DAYS, MIN_COINS_BREADTH = 0.5, 7, 8
PERIODS = {"descubrimiento": ("2019-01-01", "2023-12-31"), "confirmacion": ("2024-01-01", "2026-10-31"),
           "todo": ("2019-01-01", "2026-10-31")}
N_TESTS = len(ALL_LABELS) * len(HORIZONS)            # 24 pruebas
ALPHA_DISC = 0.05 / N_TESTS                          # Bonferroni ≈ 0.0021
ALPHA_CONF = 0.05
MIN_EP_DISC, MIN_EP_CONF = 10, 4                     # episodios de mercado mínimos
CORE = ("BTCUSDT", "ETHUSDT")                        # control sin sesgo de supervivencia
N_PERM = 2000
SEED = 20261031
DISCLAIMER = ("Contexto estadístico, no señal de compra ni de venta ni garantía. Pocos episodios independientes; "
              "el universo se eligió hoy (sesgo de supervivencia).")


# ======================================================================================
# Etiquetas por moneda
# ======================================================================================
def _pct_prior(values: np.ndarray, width: int, strict: bool) -> np.ndarray:
    """Para cada posición i: fracción de los `width` valores PREVIOS (i-width … i-1) menores (o menores/iguales) que values[i].
    NaN si falta cualquier dato en la ventana o en el valor."""
    n = len(values)
    out = np.full(n, np.nan)
    if n <= width:
        return out
    win = sliding_window_view(values, width)[: n - width]          # win[j] = values[j : j+width]; previo de i=j+width
    cur = values[width:]
    bad = np.isnan(win).any(axis=1) | np.isnan(cur)
    cmp = (win < cur[:, None]) if strict else (win <= cur[:, None])
    res = cmp.mean(axis=1)
    res[bad] = np.nan
    out[width:] = res
    return out


def coin_features(close: pd.Series) -> pd.DataFrame:
    """Etiquetas y descriptivas de UNA moneda. `close`: cierres diarios UTC (índice de fechas, sin huecos: los faltantes son NaN).
    Cada etiqueta trae su columna `ready_*` (hay ventana completa para evaluarla); donde no hay ventana no se etiqueta."""
    c = close.astype(float)
    w = WINDOW - 1
    prev_min = c.rolling(w, min_periods=w).min().shift(1)
    prev_max = c.rolling(w, min_periods=w).max().shift(1)
    ready_range = prev_min.notna() & c.notna()
    lr = np.log(c).diff()
    ret7 = np.log(c / c.shift(7))
    r7_min = ret7.rolling(w, min_periods=w).min().shift(1)
    r7_max = ret7.rolling(w, min_periods=w).max().shift(1)
    ready_week = r7_min.notna() & ret7.notna()
    vol30 = lr.rolling(30, min_periods=30).std()
    vpct = pd.Series(_pct_prior(vol30.to_numpy(), WINDOW, strict=True), index=c.index)
    ready_vol = vpct.notna()
    min365 = c.rolling(WINDOW, min_periods=WINDOW).min()
    max365 = c.rolling(WINDOW, min_periods=WINDOW).max()
    days_since_min = c.rolling(WINDOW, min_periods=WINDOW).apply(lambda x: len(x) - 1 - int(np.argmin(x)), raw=True)
    return pd.DataFrame({
        "close": c, "vol30": vol30, "ret7": ret7,
        "min12m": ready_range & (c <= prev_min), "max12m": ready_range & (c >= prev_max),
        "peor_semana": ready_week & (ret7 <= r7_min), "mejor_semana": ready_week & (ret7 >= r7_max),
        "vol_baja": ready_vol & (vpct <= VOL_PCT_LOW), "vol_alta": ready_vol & (vpct >= VOL_PCT_HIGH),
        "ready_min12m": ready_range, "ready_max12m": ready_range,
        "ready_peor_semana": ready_week, "ready_mejor_semana": ready_week,
        "ready_vol_baja": ready_vol, "ready_vol_alta": ready_vol,
        # descriptivas (se muestran, no se evalúan)
        "pct_rank": pd.Series(_pct_prior(c.to_numpy(), w, strict=False), index=c.index),
        "vol_pct": vpct,
        "dist_min": c / min365 - 1.0, "dist_max": c / max365 - 1.0,
        "dd_ath": c / c.cummax() - 1.0, "days_since_min": days_since_min,
    }, index=c.index)


# ======================================================================================
# Panel (monedas × días) y etiquetas de mercado
# ======================================================================================
class Panel:
    """Todas las monedas alineadas a un calendario diario común."""

    def __init__(self, closes: dict[str, pd.Series]):
        if not closes:
            raise ValueError("sin datos")
        idx = pd.DatetimeIndex(sorted(set().union(*[set(s.index) for s in closes.values()])))
        full = pd.date_range(idx.min(), idx.max(), freq="D")
        self.dates = full
        self.coins = list(closes)
        self.feats = {k: coin_features(closes[k].reindex(full)) for k in self.coins}
        self.close = np.vstack([self.feats[k]["close"].to_numpy() for k in self.coins])
        C, T = self.close.shape
        self.flags: dict[str, np.ndarray] = {}
        self.ready: dict[str, np.ndarray] = {}
        for lab in COIN_LABELS:
            self.flags[lab] = np.vstack([self.feats[k][lab].to_numpy(dtype=bool) for k in self.coins])
            self.ready[lab] = np.vstack([self.feats[k]["ready_" + lab].to_numpy(dtype=bool) for k in self.coins])
        # amplitud: share de monedas con ventana completa que tuvieron mínimo/máximo de 12 m en los últimos 7 días
        rdy = self.ready["min12m"]
        n_elig = rdy.sum(axis=0)
        for lab, src in (("capitulacion_amplia", "min12m"), ("euforia_amplia", "max12m")):
            recent = (pd.DataFrame(self.flags[src].T.astype(float)).rolling(BREADTH_DAYS, min_periods=1).max().to_numpy().T > 0) & rdy
            with np.errstate(invalid="ignore", divide="ignore"):
                share = np.where(n_elig > 0, recent.sum(axis=0) / np.maximum(n_elig, 1), 0.0)
            day_flag = (n_elig >= MIN_COINS_BREADTH) & (share >= BREADTH_SHARE)
            self.flags[lab] = day_flag[None, :] & rdy
            self.ready[lab] = rdy & (n_elig >= MIN_COINS_BREADTH)[None, :]
            setattr(self, "breadth_" + src, share)
        self.n_eligible = n_elig

    def idx_range(self, period: str) -> np.ndarray:
        lo, hi = PERIODS[period]
        return np.asarray((self.dates >= pd.Timestamp(lo)) & (self.dates <= pd.Timestamp(hi)))


def episode_starts(F: np.ndarray, gap: int = GAP) -> np.ndarray:
    """Primer día de cada episodio (fila = moneda): días con etiqueta separados por menos de `gap` días son un mismo episodio."""
    C, T = F.shape
    idx = np.arange(T)[None, :]
    last = np.maximum.accumulate(np.where(F, idx, -10 ** 9), axis=1)
    prev = np.concatenate([np.full((C, 1), -10 ** 9), last[:, :-1]], axis=1)
    return F & ((idx - prev) >= gap)


def count_market_episodes(starts: np.ndarray, gap: int = GAP) -> int:
    """Episodios de mercado: fechas con episodios de cualquier moneda, agrupadas si están a menos de `gap` días."""
    days = np.flatnonzero(starts.any(axis=0))
    if len(days) == 0:
        return 0
    return int(1 + (np.diff(days) >= gap).sum())


def _forward(close: np.ndarray, h: int) -> np.ndarray:
    out = np.full_like(close, np.nan)
    out[:, : close.shape[1] - h] = np.log(close[:, h:] / close[:, : close.shape[1] - h])
    return out


def _median(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    return float(np.median(x)) if len(x) else float("nan")


def evaluate(panel: Panel, label: str, h: int, period: str, n_perm: int = N_PERM, seed: int = SEED,
             rows: list[int] | None = None, with_events: bool = False) -> dict:
    """Resultado a h días tras los episodios de `label` dentro de `period`, frente a la mediana de la misma moneda en el mismo periodo."""
    fwd = _forward(panel.close, h)
    in_p = panel.idx_range(period)[None, :]
    elig = panel.ready[label] & np.isfinite(fwd) & in_p
    if rows is not None:
        keep = np.zeros(elig.shape[0], dtype=bool)
        keep[rows] = True
        elig = elig & keep[:, None]
    base = np.array([_median(fwd[c][elig[c]]) if elig[c].any() else np.nan for c in range(elig.shape[0])])
    exc = np.where(elig, fwd - base[:, None], np.nan)
    F_full = panel.flags[label]
    starts = episode_starts(F_full) & elig
    n_ev = int(starts.sum())
    res = {"label": label, "h": h, "period": period, "n_eventos": n_ev, "n_monedas": int(starts.any(axis=1).sum()),
           "n_episodios_mercado": count_market_episodes(starts), "dias_elegibles": int(elig.sum())}
    if n_ev == 0:
        res.update(mediana=None, pct_positivo=None, base=None, exceso=None, p=None)
        return res
    ev_fwd = fwd[starts]
    stat = _median(exc[starts])
    res.update(mediana=_median(ev_fwd), pct_positivo=float((ev_fwd > 0).mean()), base=_median(fwd[elig]), exceso=stat)
    if n_perm > 0:
        rng = np.random.default_rng(seed + 7919 * h + 31 * ALL_LABELS.index(label))
        T = F_full.shape[1]
        valid = hit = 0
        for _ in range(n_perm):
            s = int(rng.integers(GAP, max(GAP + 1, T - GAP)))
            st = episode_starts(np.roll(F_full, s, axis=1)) & elig
            if not st.any():
                continue
            valid += 1
            if abs(_median(exc[st])) >= abs(stat):
                hit += 1
        res["p"] = float((1 + hit) / (1 + valid)) if valid else None
    else:
        res["p"] = None
    if with_events:
        cs, ts = np.nonzero(starts)
        res["_events"] = [(int(c), int(t), float(exc[c, t])) for c, t in zip(cs, ts)]
    return res


def _sign(x) -> int:
    return 0 if x is None or not np.isfinite(x) else (1 if x > 0 else -1 if x < 0 else 0)


def verdict(disc: dict, conf: dict, core_sign_ok: bool, year_ok: bool) -> tuple[str, str]:
    """Aplica los criterios del pre-registro. Devuelve (veredicto, motivo)."""
    if disc["n_episodios_mercado"] < MIN_EP_DISC:
        return "sin veredicto", f"muestra pequeña en descubrimiento ({disc['n_episodios_mercado']} episodios de mercado, mínimo {MIN_EP_DISC})"
    if conf["n_episodios_mercado"] < MIN_EP_CONF:
        return "sin veredicto", f"muestra pequeña en confirmación ({conf['n_episodios_mercado']} episodios de mercado, mínimo {MIN_EP_CONF})"
    fails = []
    if disc["p"] is None or disc["p"] >= ALPHA_DISC:
        fails.append(f"descubrimiento no significativo (p={disc['p']:.3f}, umbral {ALPHA_DISC:.4f})" if disc["p"] is not None else "sin p en descubrimiento")
    if _sign(conf["exceso"]) != _sign(disc["exceso"]) or _sign(disc["exceso"]) == 0:
        fails.append("la confirmación no tiene el mismo signo")
    elif conf["p"] is None or conf["p"] >= ALPHA_CONF:
        fails.append(f"confirmación no significativa (p={conf['p']:.3f})" if conf["p"] is not None else "sin p en confirmación")
    if not core_sign_ok:
        fails.append("no se sostiene en BTC+ETH solos")
    if not year_ok:
        fails.append("depende de un solo año")
    return ("con evidencia", "cumple los 4 criterios") if not fails else ("sin evidencia suficiente", "; ".join(fails))


def run_label(panel: Panel, label: str, h: int, n_perm: int = N_PERM) -> dict:
    disc = evaluate(panel, label, h, "descubrimiento", n_perm)
    conf = evaluate(panel, label, h, "confirmacion", n_perm)
    allp = evaluate(panel, label, h, "todo", 0, with_events=True)
    core_rows = [panel.coins.index(c) for c in CORE if c in panel.coins]
    core = evaluate(panel, label, h, "todo", 0, rows=core_rows) if core_rows else {"exceso": None}
    core_ok = _sign(core.get("exceso")) == _sign(disc.get("exceso")) != 0
    # criterio 4: al quitar el año con más episodios, el signo se mantiene
    ev = allp.pop("_events", [])
    year_ok = False
    if ev:
        yrs = pd.Series([panel.dates[t].year for _, t, _ in ev])
        top = yrs.value_counts().idxmax()
        rest = [e for (e, y) in zip([x[2] for x in ev], yrs) if y != top]
        year_ok = bool(rest) and _sign(float(np.median(rest))) == _sign(disc.get("exceso")) != 0
    v, why = verdict(disc, conf, core_ok, year_ok) if disc["n_eventos"] and conf["n_eventos"] else ("sin veredicto", "sin episodios en algún periodo")
    keep = ("n_eventos", "n_monedas", "n_episodios_mercado", "mediana", "pct_positivo", "base", "exceso", "p")
    return {"label": label, "h": h, "veredicto": v, "motivo": why,
            "descubrimiento": {k: disc[k] for k in keep}, "confirmacion": {k: conf[k] for k in keep},
            "todo": {k: allp[k] for k in keep}, "btc_eth_exceso": core.get("exceso")}


def vol_control(panel: Panel, label: str, period: str = "todo", h: int = 30) -> dict:
    """Control del método para vol_baja/vol_alta: ¿la volatilidad futura (30 d) se parece a la actual? (persistencia esperada)."""
    vol = np.vstack([panel.feats[k]["vol30"].to_numpy() for k in panel.coins])
    fut = np.full_like(vol, np.nan)
    fut[:, : vol.shape[1] - h] = vol[:, h:]
    ratio = fut / vol
    elig = panel.ready[label] & np.isfinite(ratio) & panel.idx_range(period)[None, :]
    st = episode_starts(panel.flags[label]) & elig
    return {"label": label, "n_eventos": int(st.sum()), "ratio_mediano_tras_evento": _median(ratio[st]),
            "ratio_mediano_base": _median(ratio[elig])}


# ======================================================================================
# Estado de hoy (alertas)
# ======================================================================================
def today_state(panel: Panel, results: dict | None = None) -> dict:
    """Estado del último día de datos: descriptivas por moneda, etiquetas activas y, si hay resultados, la estadística histórica al lado."""
    t = len(panel.dates) - 1
    coins = []
    for k in panel.coins:
        f = panel.feats[k].iloc[t]
        if not np.isfinite(f["close"]):
            continue
        active = [lab for lab in COIN_LABELS if bool(f[lab])]
        coins.append({"symbol": k, "close": float(f["close"]),
                      "pct_rank": None if not np.isfinite(f["pct_rank"]) else float(f["pct_rank"]),
                      "dist_min": None if not np.isfinite(f["dist_min"]) else float(f["dist_min"]),
                      "dist_max": None if not np.isfinite(f["dist_max"]) else float(f["dist_max"]),
                      "dd_ath": float(f["dd_ath"]),
                      "days_since_min": None if not np.isfinite(f["days_since_min"]) else int(f["days_since_min"]),
                      "ret7": None if not np.isfinite(f["ret7"]) else float(np.expm1(f["ret7"])),
                      "vol_pct": None if not np.isfinite(f["vol_pct"]) else float(f["vol_pct"]),
                      "etiquetas": active})
    market = [lab for lab in MARKET_LABELS if bool(panel.flags[lab][:, t].any())]
    out = {"fecha": str(panel.dates[t].date()), "monedas": coins, "etiquetas_mercado": market,
           "amplitud": {"monedas_con_ventana": int(panel.n_eligible[t]),
                        "cerca_de_minimos_7d": float(panel.breadth_min12m[t]), "cerca_de_maximos_7d": float(panel.breadth_max12m[t])}}
    if results:
        lookup = {}
        for lab in ALL_LABELS:
            lookup[lab] = [{"h": h, **{k: results[lab][h][k] for k in ("veredicto", "motivo")},
                            "n_episodios_mercado": results[lab][h]["todo"]["n_episodios_mercado"],
                            "mediana": results[lab][h]["todo"]["mediana"], "pct_positivo": results[lab][h]["todo"]["pct_positivo"],
                            "exceso": results[lab][h]["todo"]["exceso"]} for h in HORIZONS if h in results[lab]]
        out["historico_por_etiqueta"] = lookup
    out["aviso"] = DISCLAIMER
    return out


def run_phase0(closes: dict[str, pd.Series], n_perm: int = N_PERM, progress=None) -> dict:
    """Corre las 8 etiquetas × 3 horizontes y devuelve resultados + estado de hoy."""
    panel = Panel(closes)
    results: dict[str, dict] = {lab: {} for lab in ALL_LABELS}
    for lab in ALL_LABELS:
        for h in HORIZONS:
            results[lab][h] = run_label(panel, lab, h, n_perm)
            if progress:
                progress(lab, h, results[lab][h])
    controls = {lab: vol_control(panel, lab) for lab in ("vol_baja", "vol_alta")}
    return {"results": results, "vol_control": controls, "hoy": today_state(panel, results),
            "params": {"window": WINDOW, "gap": GAP, "horizontes": list(HORIZONS), "n_perm": n_perm, "seed": SEED,
                       "alfa_descubrimiento": ALPHA_DISC, "alfa_confirmacion": ALPHA_CONF, "periodos": PERIODS,
                       "monedas": panel.coins, "desde": str(panel.dates[0].date()), "hasta": str(panel.dates[-1].date())}}
