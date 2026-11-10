"""Observatorio de mercado · evaluación de las fases 1 y 3 (variables de flujo y de tono contra retorno y volatilidad futuros a 7 días).

Criterio fijado en OBSERVATORIO_MERCADO.md: una variable "aporta" solo si |ρ| ≥ 0.15 con n ≥ 120 observaciones diarias, el mismo signo en las dos
mitades del periodo, y (para volatilidad) controlando por la volatilidad previa. ρ = correlación de rangos (Spearman), parcial: se quitan
primero los controles (retorno previo de 7 días; volatilidad de 30 días; Fear & Greed en la fase 3).
Las ventanas de 7 días se traslapan día a día, así que el n efectivo es ≈ n/7: se informa y NO se usa para relajar nada.
Antes de 120 días el resultado es "sin veredicto".
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_N = 120
THRESH = 0.15
H = 7


def asset_frame(close: pd.Series) -> pd.DataFrame:
    """Para cada día d (la foto se toma poco después de las 00:00 UTC): objetivos y bases medidos desde el cierre de d-1.
      ret7  = log(cierre[d+6] / cierre[d-1])        (retorno de los 7 días que empiezan en d)
      rv7   = √Σ r² de los 7 días d … d+6           (volatilidad realizada)
      prior7 = log(cierre[d-1] / cierre[d-8])       vol30 = desv. est. diaria de los 30 días previos (× √7 = base de volatilidad)"""
    c = close.astype(float)
    r = np.log(c / c.shift(1))
    return pd.DataFrame({
        "close_asof": c.shift(1),
        "ret7": np.log(c.shift(-(H - 1)) / c.shift(1)),
        "rv7": np.sqrt(r.pow(2).rolling(H).sum().shift(-(H - 1))),
        "prior7": np.log(c.shift(1) / c.shift(H + 1)),
        "vol30": r.rolling(30).std().shift(1) * np.sqrt(H),
    })


def partial_spearman(y, x, controls=()) -> tuple[float, int]:
    cols = {"y": np.asarray(y, float), "x": np.asarray(x, float)}
    for i, c in enumerate(controls):
        cols[f"c{i}"] = np.asarray(c, float)
    d = pd.DataFrame(cols).replace([np.inf, -np.inf], np.nan).dropna()
    n = len(d)
    if n < 10:
        return float("nan"), n
    R = d.rank()
    if controls:
        Z = np.column_stack([np.ones(n)] + [R[f"c{i}"].to_numpy() for i in range(len(controls))])
        res = {}
        for k in ("x", "y"):
            beta, *_ = np.linalg.lstsq(Z, R[k].to_numpy(), rcond=None)
            res[k] = R[k].to_numpy() - Z @ beta
        a, b = res["x"], res["y"]
    else:
        a, b = R["x"].to_numpy(), R["y"].to_numpy()
    if a.std() == 0 or b.std() == 0:
        return float("nan"), n
    return float(np.corrcoef(a, b)[0, 1]), n


def evaluate_pair(df: pd.DataFrame, feature: str, target: str, controls: list[str]) -> dict:
    """ρ parcial de `feature` contra `target` (controlando por `controls`), con las dos mitades del periodo."""
    d = df[[feature, target] + controls].replace([np.inf, -np.inf], np.nan).dropna()
    n = len(d)
    out = {"feature": feature, "target": target, "n": n, "n_efectivo": n // H, "rho": None, "rho_mitad1": None, "rho_mitad2": None,
           "veredicto": "sin veredicto", "motivo": f"faltan datos ({n} de {MIN_N} días)"}
    if n < 10:
        return out
    ctl = lambda x: [x[c] for c in controls]
    rho, _ = partial_spearman(d[target], d[feature], ctl(d))
    out["rho"] = None if not np.isfinite(rho) else rho
    if n < MIN_N:
        return out
    h = n // 2
    r1, _ = partial_spearman(d[target].iloc[:h], d[feature].iloc[:h], ctl(d.iloc[:h]))
    r2, _ = partial_spearman(d[target].iloc[h:], d[feature].iloc[h:], ctl(d.iloc[h:]))
    out["rho_mitad1"] = None if not np.isfinite(r1) else r1
    out["rho_mitad2"] = None if not np.isfinite(r2) else r2
    if out["rho"] is None or out["rho_mitad1"] is None or out["rho_mitad2"] is None:
        out["motivo"] = "correlación no calculable"
    elif abs(rho) >= THRESH and np.sign(r1) == np.sign(r2) == np.sign(rho):
        out["veredicto"], out["motivo"] = "aporta", f"|ρ|={abs(rho):.2f} ≥ {THRESH} y el signo se repite en las dos mitades"
    else:
        out["veredicto"], out["motivo"] = "sin evidencia suficiente", f"ρ={rho:+.2f} (mitades {r1:+.2f} / {r2:+.2f})"
    return out


def flow_daily(rows: list[dict], cols: list[str]) -> pd.DataFrame:
    """Una fila por día UTC: la PRIMERA foto del día (≈00:07 UTC, la misma hora de las predicciones)."""
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=cols)
    df["date"] = pd.to_datetime(df["ts"], unit="ms").dt.normalize()
    return df.sort_values("ts").groupby("date").first().drop(columns=["ts"])


FLOW_FEATURES = ["taker_buy_ratio_24h", "book_imb_top100", "okx_funding", "okx_ls_ratio", "okx_taker_buy_ratio_1h", "kc_funding",
                 "coinbase_premium", "liq_imb", "oi_chg_1d", "dvol_minus_vol30"]
GLOBAL_FEATURES = ["stable_chg_7d", "fng"]


def evaluate_flows(daily: pd.DataFrame, closes: dict[str, pd.Series]) -> list[dict]:
    """Cada variable de flujo contra retorno (control: retorno previo) y volatilidad (control: vol de 30 d) de los 7 días siguientes."""
    out = []
    for a in ("btc", "eth"):
        cs = closes.get(a.upper() + "USDT")
        if cs is None or daily.empty:
            continue
        fr = asset_frame(cs).reindex(daily.index)
        d = pd.DataFrame(index=daily.index)
        for k in ("taker_buy_ratio_24h", "book_imb_top100", "okx_funding", "okx_ls_ratio", "okx_taker_buy_ratio_1h", "kc_funding", "coinbase_premium"):
            d[k] = daily.get(f"{a}_{k}")
        ll, ls = daily.get(f"{a}_liq_long_usd"), daily.get(f"{a}_liq_short_usd")
        d["liq_imb"] = (ll - ls) / (ll + ls).replace(0, np.nan) if ll is not None else np.nan
        oi = daily.get(f"{a}_okx_oi_usd")
        d["oi_chg_1d"] = oi.pct_change() if oi is not None else np.nan
        dv = daily.get(f"{a}_dvol")
        d["dvol_minus_vol30"] = dv / 100 / np.sqrt(365) * np.sqrt(H) - fr["vol30"] if dv is not None else np.nan
        for g in GLOBAL_FEATURES:
            d[g] = daily.get(g)
        d["ret7"], d["rv7"], d["prior7"], d["vol30"] = fr["ret7"], fr["rv7"], fr["prior7"], fr["vol30"]
        for f in FLOW_FEATURES + GLOBAL_FEATURES:
            if f not in d or d[f].notna().sum() == 0:
                continue
            for tgt, ctl in (("ret7", ["prior7"]), ("rv7", ["vol30"])):
                r = evaluate_pair(d, f, tgt, ctl)
                r["asset"] = a.upper()
                out.append(r)
    return out


def evaluate_sentiment(tone: pd.DataFrame, closes: dict[str, pd.Series], fng: pd.Series | None = None) -> list[dict]:
    """Tono del día contra retorno/volatilidad de los 7 días siguientes, controlando por retorno previo, vol de 30 d y Fear & Greed."""
    out = []
    if tone.empty:
        return out
    for a, col in (("BTC", "tone_btc"), ("ETH", "tone_eth"), ("BTC", "tone"), ("BTC", "st_balance")):
        cs = closes.get(a + "USDT")
        if cs is None or col not in tone:
            continue
        fr = asset_frame(cs).reindex(tone.index)
        d = fr.copy()
        d[col] = tone[col]
        d["fng"] = fng.reindex(tone.index) if fng is not None else np.nan
        ctl_ret = ["prior7"] + (["fng"] if d["fng"].notna().sum() else [])
        for tgt, ctl in (("ret7", ctl_ret), ("rv7", ["vol30"] + (["fng"] if d["fng"].notna().sum() else []))):
            r = evaluate_pair(d, col, tgt, ctl)
            r["asset"] = a
            out.append(r)
    return out
