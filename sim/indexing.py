"""Pesos de un índice (funciones puras, sin red ni estado): fáciles de probar.

  capped_weights(raw, cap)            pesos proporcionales a `raw`, con tope por moneda y el exceso repartido
  index_weights(raw, cap, min_weight) además omite las monedas que quedarían por debajo de `min_weight`

Método de tope (el estándar de los índices con límite de concentración): si alguna moneda pasa el tope, se fija en el tope y
el resto del peso se reparte entre las demás en proporción a su `raw`; se repite hasta que ninguna lo pase.
"""
from __future__ import annotations

from typing import Optional


def capped_weights(raw: dict, cap: Optional[float] = None) -> dict:
    pos = {k: float(v) for k, v in raw.items() if v and float(v) > 0}
    n = len(pos)
    if n == 0:
        return {}
    if cap is not None and cap * n < 1 - 1e-9:
        raise ValueError(f"Tope imposible: {n} monedas con tope {cap:.0%} suman menos de 100 %")
    total = sum(pos.values())
    w = {k: v / total for k, v in pos.items()}
    if cap is None:
        return w
    fixed: set = set()
    for _ in range(n + 1):
        over = {k for k, x in w.items() if k not in fixed and x > cap + 1e-12}
        if not over:
            break
        fixed |= over
        rest = {k: v for k, v in pos.items() if k not in fixed}
        if not rest:                                             # todas topadas: cap * n == 1
            return {k: 1.0 / n for k in pos}
        free = 1.0 - cap * len(fixed)
        rs = sum(rest.values())
        w = {**{k: cap for k in fixed}, **{k: free * v / rs for k, v in rest.items()}}
    return w


def index_weights(raw: dict, cap: Optional[float] = None, min_weight: float = 0.0) -> dict:
    """Pesos con tope y con piso práctico: lo que quedaría bajo `min_weight` no se compra (no cabe en el monto mínimo de
    una orden) y su peso se reparte entre las demás, volviendo a aplicar el tope. Devuelve {} si no hay precios válidos."""
    active = {k: v for k, v in raw.items() if v and float(v) > 0}
    for _ in range(len(active) + 1):
        if not active:
            return {}
        w = capped_weights(active, cap if cap is None or cap * len(active) >= 1 - 1e-9 else None)
        small = [k for k, x in w.items() if x < min_weight]
        if not small or len(small) == len(w):
            return w
        for k in small:
            active.pop(k)
    return w
