"""Interruptores de régimen (solo para backtests; ver BACKTEST_V2_2019_2024.md).

`btc_vol_gate`: encendido cuando la volatilidad anualizada de BTC en los últimos `lookback_days` días supera `threshold`.
Regla fijada de antemano (no se ajusta con resultados):
  * se evalúa UNA vez por día UTC, en la vela de las 00:00, con los cierres de las 23:00 de los días ANTERIORES
    (nunca con información de la vela en curso);
  * volatilidad = desviación estándar (n-1) de `lookback_days` retornos diarios (cierre de 23:00 a cierre de 23:00) × √365;
  * entre evaluaciones conserva su estado; antes de la primera evaluación está apagado.
"""
from __future__ import annotations

import math

import numpy as np

HOUR_MS = 3_600_000


def btc_vol_gate(close: np.ndarray, ts_ms: np.ndarray, lookback_days: int = 14, threshold: float = 0.40,
                 bar_ms: int = HOUR_MS) -> np.ndarray:
    if bar_ms != HOUR_MS:
        raise ValueError("El interruptor de volatilidad solo está definido para velas de 1 h")
    n, per = len(close), 24
    out = np.zeros(n, dtype=bool)
    state, first = False, True
    back = per * np.arange(lookback_days + 1)
    for i in range(n):
        hour = (int(ts_ms[i]) // HOUR_MS) % 24
        can = i - 1 - per * lookback_days >= 0
        if can and (hour == 0 or first):
            c = close[i - 1 - back]                        # cierres de las 23:00, del más reciente al más antiguo
            if np.all(np.isfinite(c)) and np.all(c > 0):
                r = c[:-1] / c[1:] - 1.0
                state = bool(r.std(ddof=1) * math.sqrt(365) > threshold)
                first = False
        out[i] = state
    return out
