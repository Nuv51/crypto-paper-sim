"""Observatorio de mercado · predicciones registradas con fecha y medidas después (BTC y ETH, horizonte 7 días).

NO es un modelo de precio. Se registran dos cosas, cada día con la foto de ≈00:07 UTC y el cierre del día anterior:
  1) P(retorno a 7 días > 0): modelo inicial = frecuencia base de los retornos de 7 días ya CONOCIDOS en los últimos 365 días (sin mirar adelante).
     Cualquier modelo posterior debe superarla en Brier skill score con ≥ 90 predicciones resueltas, o no cuenta.
  2) Volatilidad realizada a 7 días (√Σr²): tres pronósticos — vol de 30 días (línea base), EWMA(0.94) y DVOL de Deribit si hay.
Cuando pasan los 7 días se resuelve cada una y se miden Brier y pérdidas de volatilidad (MAE y QLIKE). El tablero muestra el historial completo,
aunque salga mal: es la forma de no engañarse con un pronóstico convincente.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

H = 7
MIN_RESOLVED = 90
EWMA_LAMBDA = 0.94


def vol_forecasts(close: pd.Series, dvol: float | None = None) -> dict:
    """close: cierres diarios hasta el día `asof` INCLUSIVE (el último es el cierre de la víspera de la foto)."""
    r = np.log(close.astype(float) / close.astype(float).shift(1)).dropna()
    if len(r) < 60:
        return {"vol30": None, "ewma": None, "dvol": None}
    out = {"vol30": float(r.tail(30).std() * np.sqrt(H))}
    w = EWMA_LAMBDA ** np.arange(len(r))[::-1]
    out["ewma"] = float(np.sqrt(np.sum(w * r.to_numpy() ** 2) / np.sum(w)) * np.sqrt(H))
    out["dvol"] = float(dvol / 100.0 / np.sqrt(365.0) * np.sqrt(H)) if dvol else None
    return out


def base_rate_up(close: pd.Series, window: int = 365) -> float | None:
    """Frecuencia de retornos de 7 días > 0 entre los que YA terminaron (terminan en o antes del cierre de la víspera)."""
    c = close.astype(float)
    ret = np.log(c / c.shift(H)).dropna().tail(window)
    return float((ret > 0).mean()) if len(ret) >= 120 else None


def make_prediction(asset: str, close: pd.Series, asof_date: str, dvol: float | None = None) -> dict | None:
    """`close` debe terminar en el cierre de `asof_date` (la víspera de la foto)."""
    p = base_rate_up(close)
    v = vol_forecasts(close, dvol)
    if p is None or v["vol30"] is None:
        return None
    return {"id": f"{asset}:{asof_date}", "asset": asset, "asof": asof_date, "h": H, "p_up": p, "vol30": v["vol30"], "ewma": v["ewma"], "dvol": v["dvol"],
            "close_asof": float(close.iloc[-1]), "resolved": False}


def resolve(preds: list[dict], closes: dict[str, pd.Series]) -> int:
    """Rellena el resultado de las predicciones cuyos 7 días ya pasaron (cierres diarios ya disponibles). Devuelve cuántas resolvió."""
    n = 0
    for p in preds:
        if p.get("resolved"):
            continue
        cs = closes.get(p["asset"] + "USDT")
        if cs is None:
            continue
        d0 = pd.Timestamp(p["asof"])
        end = d0 + pd.Timedelta(days=H)
        if d0 not in cs.index or end not in cs.index:
            continue
        seg = cs.loc[d0:end].astype(float)
        if len(seg) != H + 1:
            continue                                        # hueco en los datos: no se resuelve con información incompleta
        r = np.log(seg / seg.shift(1)).dropna()
        p.update(resolved=True, ret7=float(np.log(seg.iloc[-1] / seg.iloc[0])), up=int(seg.iloc[-1] > seg.iloc[0]), rv7=float(np.sqrt((r ** 2).sum())))
        n += 1
    return n


def merge_predictions(store: list[dict], new: list[dict]) -> list[dict]:
    have = {p["id"] for p in store}
    return sorted(store + [p for p in new if p["id"] not in have], key=lambda p: (p["asof"], p["asset"]))


def score(preds: list[dict]) -> dict:
    res = [p for p in preds if p.get("resolved")]
    out = {"n_total": len(preds), "n_resueltas": len(res), "minimo": MIN_RESOLVED, "por_activo": {}}
    for a in sorted({p["asset"] for p in res}):
        rs = [p for p in res if p["asset"] == a]
        y = np.array([p["up"] for p in rs], float)
        pu = np.array([p["p_up"] for p in rs], float)
        brier, brier_half = float(np.mean((pu - y) ** 2)), float(np.mean((0.5 - y) ** 2))
        vol = {}
        for k in ("vol30", "ewma", "dvol"):
            pairs = [(p[k], p["rv7"]) for p in rs if p.get(k) and p["rv7"] > 0]
            if pairs:
                f, rv = np.array(pairs).T
                vol[k] = {"n": len(pairs), "mae": float(np.mean(np.abs(f - rv))),
                          "qlike": float(np.mean(np.log(f ** 2) + rv ** 2 / f ** 2)),
                          "sesgo": float(np.mean(f / rv - 1))}
        out["por_activo"][a] = {"n": len(rs), "acierto_direccion": float(np.mean((pu > 0.5) == (y == 1))), "brier": brier, "brier_vs_0_5": brier_half,
                                "brier_skill_vs_0_5": float(1 - brier / brier_half) if brier_half > 0 else None, "vol": vol,
                                "mejor_vol_qlike": min(vol, key=lambda k: vol[k]["qlike"]) if vol else None}
    out["veredicto"] = ("sin veredicto" if len(res) < MIN_RESOLVED else "evaluable")
    out["aviso"] = "Estimación estadística registrada con fecha; no es una garantía ni un consejo. El modelo inicial de dirección es solo la frecuencia base."
    return out
