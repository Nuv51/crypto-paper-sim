"""Indicadores técnicos CAUSALES: el valor en la barra t solo usa datos de t y anteriores.

Eso permite precalcularlos sobre todo el historial en el replay sin mirar al futuro
(tests/test_accounting.py lo verifica comparando contra el cálculo sobre datos truncados).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """RSI de Wilder."""
    d = close.diff()
    gain = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(loss != 0, 100.0).where(gain.notna())


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0):
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=n).std(ddof=0)
    return mid, mid + k * sd, mid - k * sd


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Average True Range (Wilder)."""
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - pc).abs(),
                    (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def donchian_high(df: pd.DataFrame, n: int) -> pd.Series:
    """Máximo de las n barras ANTERIORES (excluye la actual, para detectar la ruptura)."""
    return df["high"].rolling(n, min_periods=n).max().shift(1)


def donchian_low(df: pd.DataFrame, n: int) -> pd.Series:
    return df["low"].rolling(n, min_periods=n).min().shift(1)


def roc(close: pd.Series, n: int) -> pd.Series:
    return close / close.shift(n) - 1.0
