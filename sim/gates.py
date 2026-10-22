"""Interruptores de régimen (solo para backtests; ver BACKTEST_V2_2019_2024.md).

`btc_vol_gate`: encendido cuando la volatilidad anualizada de BTC en los últimos `lookback_days` días supera `threshold`.
Regla fijada de antemano (no se ajusta con resultados):
  * se evalúa UNA vez por día UTC, en la primera vela del día (las 00:00), con los cierres de las 23:00 de los días ANTERIORES
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
    """Se evalúa en la PRIMERA vela de cada día UTC (la de las 00:00 salvo que falte por mantenimiento del exchange).
    Los cierres de las 23:00 se buscan POR HORA (no por posición), así los huecos de datos no desplazan la ventana: si falta
    la vela exacta se usa la última anterior. Sin información de la vela en curso."""
    if bar_ms != HOUR_MS:
        raise ValueError("El interruptor de volatilidad solo está definido para velas de 1 h")
    ts = np.asarray(ts_ms, dtype=np.int64)
    n, day_ms = len(close), 24 * HOUR_MS
    out = np.zeros(n, dtype=bool)
    state, last_day = False, None
    ks = np.arange(lookback_days + 1)
    for i in range(n):
        day = int(ts[i]) // day_ms
        if day != last_day:
            last_day = day
            targets = ts[i] - HOUR_MS - day_ms * ks               # cierres de las 23:00 de los días anteriores (más reciente primero)
            if targets[-1] >= ts[0]:
                pos = np.searchsorted(ts, targets, side="right") - 1
                c = close[pos]
                if np.all(np.isfinite(c)) and np.all(c > 0):
                    r = c[:-1] / c[1:] - 1.0
                    state = bool(r.std(ddof=1) * math.sqrt(365) > threshold)
        out[i] = state
    return out


def btc_sma_gate(close: np.ndarray, ts_ms: np.ndarray, sma_days: int = 200, bar_ms: int = HOUR_MS) -> np.ndarray:
    """Filtro de tendencia (V3): encendido cuando el último cierre diario de BTC está POR ENCIMA de su media simple de `sma_days` días.
    Regla fijada de antemano (estándar de la industria; no se ajusta con resultados):
      * se evalúa una vez por día UTC, en la primera vela del día, con los cierres de las 23:00 de los `sma_days` días ANTERIORES
        (el más reciente es el cierre de ayer; nunca usa la vela en curso);
      * busca los cierres POR HORA (no por posición) para que los huecos de datos no desplacen la ventana;
      * sin historial suficiente para la media completa queda apagado.
    """
    if bar_ms != HOUR_MS:
        raise ValueError("El filtro de tendencia solo está definido para velas de 1 h")
    ts = np.asarray(ts_ms, dtype=np.int64)
    n, day_ms = len(close), 24 * HOUR_MS
    out = np.zeros(n, dtype=bool)
    state, last_day = False, None
    ks = np.arange(sma_days)
    for i in range(n):
        day = int(ts[i]) // day_ms
        if day != last_day:
            last_day = day
            targets = ts[i] - HOUR_MS - day_ms * ks
            if targets[-1] >= ts[0]:
                pos = np.searchsorted(ts, targets, side="right") - 1
                c = close[pos]
                if np.all(np.isfinite(c)) and np.all(c > 0):
                    state = bool(c[0] > c.mean())
        out[i] = state
    return out
