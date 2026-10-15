"""Perfiles de comisiones por exchange para la simulación.

Cifras verificadas el 2026-10-14 en las páginas oficiales (usuario regular, sin descuentos):
  Binance  spot VIP0 sin descuento BNB : maker 0.100% / taker 0.100%
  KuCoin   spot nivel base, Clase A    : maker 0.100% / taker 0.100%
           (las monedas Clase B/C pagan más: 0.16% / 0.24% en el nivel base)
  Bitso    mercado MXN,  tier < 20,000 : maker 0.600% / taker 0.780%
  Bitso    mercado USDT, tier < 1,000  : maker 0.300% / taker 0.360%

Las comisiones bajan con el volumen a 30 días y cambian con el tiempo: revísalas antes de sacar
conclusiones. Un edge de 0.3% por operación desaparece con un taker de 0.78%.

Simplificación: la comisión se cobra siempre en la moneda de cotización (USDT). En la vida real
algunos exchanges la cobran en la moneda base o en su token (BNB, KCS).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExchangeProfile:
    key: str
    name: str
    maker: float          # fracción: 0.001 = 0.10%
    taker: float
    min_notional: float   # USDT; en realidad varía por par (consulta exchangeInfo / symbols)
    note: str = ""


EXCHANGES: dict[str, ExchangeProfile] = {
    "binance": ExchangeProfile(
        "binance", "Binance", 0.0010, 0.0010, 5.0,
        "Spot VIP0 sin descuento BNB. Datos públicos: data-api.binance.vision / api.binance.com"),
    "kucoin": ExchangeProfile(
        "kucoin", "KuCoin", 0.0010, 0.0010, 5.0,
        "Nivel base, Clase A. Altcoins Clase B/C pagan 0.16% / 0.24%"),
    "bitso": ExchangeProfile(
        "bitso", "Bitso (mercado MXN)", 0.0060, 0.0078, 5.0,
        "Tier < 20,000 MXN. Los precios de la simulación vienen de pares USDT: es una aproximación"),
    "bitso_usdt": ExchangeProfile(
        "bitso_usdt", "Bitso (mercado USDT)", 0.0030, 0.0036, 5.0,
        "Tier < 1,000 USDT"),
}


def get_exchange(key: str) -> ExchangeProfile:
    try:
        return EXCHANGES[key]
    except KeyError as e:
        raise KeyError(f"Exchange desconocido '{key}'. Opciones: {', '.join(EXCHANGES)}") from e
