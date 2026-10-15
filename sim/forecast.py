"""Estimación estadística de tendencia (NO es una predicción confiable ni una garantía).

Ajusta una regresión lineal al log-precio de las últimas `lookback` barras y proyecta `horizon`
barras con un cono de incertidumbre basado en la volatilidad realizada (caminata aleatoria con deriva).
En la práctica el cono es MUCHO más ancho que la deriva estimada: es la forma honesta de verlo.
Simplificación: los residuos de un precio están autocorrelacionados, así que el t-stat de la pendiente
está inflado; úsalo solo como indicador relativo.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DISCLAIMER = ("Estimación estadística basada en el pasado reciente; no es una garantía ni un consejo "
              "de inversión. Los mercados cambian de régimen sin aviso.")


def trend_forecast(close: pd.Series, lookback: int = 168, horizon: int = 24) -> dict | None:
    s = close.dropna().tail(lookback)
    if len(s) < max(30, lookback // 2):
        return None
    y = np.log(s.to_numpy())
    x = np.arange(len(y), dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    fit = intercept + slope * x
    resid = y - fit
    dof = max(len(y) - 2, 1)
    s_err = np.sqrt((resid ** 2).sum() / dof)
    se_slope = s_err / np.sqrt(((x - x.mean()) ** 2).sum())
    tstat = slope / se_slope if se_slope > 0 else 0.0
    step_vol = float(np.std(np.diff(y), ddof=1))

    last = float(y[-1])
    steps = np.arange(0, horizon + 1)
    center = last + slope * steps
    band1 = step_vol * np.sqrt(steps)
    band2 = 2 * band1
    direction = "lateral / sin tendencia significativa"
    if tstat > 2:
        direction = "alcista"
    elif tstat < -2:
        direction = "bajista"
    return {
        "direction": direction, "t_stat": float(tstat),
        "slope_pct_per_bar": float(np.expm1(slope)), "step_vol": step_vol,
        "last_price": float(np.exp(last)),
        "steps": steps,
        "center": np.exp(center), "lo1": np.exp(center - band1), "hi1": np.exp(center + band1),
        "lo2": np.exp(center - band2), "hi2": np.exp(center + band2),
        "end_center": float(np.exp(center[-1])),
        "end_lo2": float(np.exp(center[-1] - band2[-1])), "end_hi2": float(np.exp(center[-1] + band2[-1])),
    }
