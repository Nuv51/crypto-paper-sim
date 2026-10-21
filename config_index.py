"""Configuración del SIMULADOR INDEXADO (pasivo): tres bots, cada uno con 10,000 USDT FICTICIOS independientes.

Qué mide: si una cartera que NO opera (solo compra el índice y rebalancea una vez al mes) le gana, o no, a los bots
activos de los otros simuladores y a BTC, descontando las mismas comisiones y deslizamiento. Es la vara de medir:
si ningún bot activo supera a esta cartera tras costos, la complejidad no está pagando.

  i01 · Top-25 ponderado por capitalización, tope 30 % por moneda
  i02 · Top-50 ponderado por capitalización, tope 30 % por moneda
  i03 · Top-25 de igual peso (4 % cada una)

UNIVERSO (congelado el 2026-10-20; NO se reconstituye durante la prueba):
  Las 50 mayores monedas por capitalización según CoinGecko (2026-10-20) que cumplen TODO esto:
    · cotizan como <MONEDA>USDT en Binance spot con estado TRADING (scripts/universe_check.py, verificado el mismo día);
    · tienen al menos 365 días de historia diaria en Binance;
    · NO son stablecoins, dinero tokenizado/fondos (BUIDL, USYC…), oro tokenizado (XAUT, PAXG), ni tokens de otros
      exchanges (WBT, LEO, OKB, CRO, BGB, HTX, GT, KCS). BNB se conserva: es una moneda grande que cotiza en Binance.
  Quedaron fuera por no cumplirlo (entre otras): XMR (Binance la retiró), TON/GRAM, HYPE (28 días de historia), CC, RAIN,
  MNT, M, KAS, PI, XDC, LIT (sin par USDT en Binance spot) y las stablecoins.
  Sesgo de supervivencia: el universo se eligió HOY con información de hoy; el índice no refleja monedas que murieron.
  Tampoco hay entradas/salidas durante la prueba (un índice real reconstituye cada trimestre): es una simplificación.

PESOS:
  · Capitalización: CAPS_USD es la capitalización de CoinGecko el 2026-10-20. Con ella y el primer precio de la
    simulación se fija un suministro implícito por moneda (cap / precio, fijo); en cada rebalanceo el peso es
    suministro × precio, limitado a 30 % por moneda (el exceso se reparte entre las demás en proporción a su capitalización).
    Una moneda cuyo peso quede bajo 0.08 % (≈ 8 USDT) se omite y el resto se renormaliza: por eso el Top-50 ponderado
    mantiene menos de 50 posiciones efectivas. Es una propiedad real de ponderar por capitalización, no un error.
  · Igual peso: 1/25 cada una.

REGLAS DE EJECUCIÓN (las del resto del proyecto): decide al cierre de la vela, se llena a la apertura de la siguiente con
comisión taker de Binance (0.10 %) y deslizamiento por nivel de liquidez (SLIPPAGE_BPS, según el volumen diario promedio
de 30 días en USDT: ≥100 M → 5 bps · ≥30 M → 8 · ≥10 M → 15 · ≥3 M → 25 · menos → 40). Rebalanceo cada 30 días en dos
tiempos (primero vende lo que sobra, a la vela siguiente compra lo que falta) para no gastar efectivo que aún no existe.
Se conserva 0.5 % en efectivo para absorber comisiones y el salto de precio entre el cierre y la apertura.

Esta cartera no tiene freno de riesgo (un índice pasivo se mantiene aunque caiga): solo hay una alerta informativa al -50 %.
Cambiar CUALQUIER parámetro invalida el estado guardado (a propósito); se reinicia con la opción `fresh` del workflow.
"""

PORTFOLIO_CAPITAL = 30_000.0      # 3 bots × 10,000 USDT FICTICIOS
INTERVAL = "1h"
PORTFOLIO_RISK = dict(max_drawdown=None, cooldown_bars=168)      # sin freno global: es una cartera pasiva

# Capitalización de mercado en USD (CoinGecko, 2026-10-20), en orden de capitalización.
CAPS_USD = {
    "BTCUSDT": 1664.369e9,
    "ETHUSDT": 298.842e9,
    "BNBUSDT": 97.757e9,
    "XRPUSDT": 84.458e9,
    "SOLUSDT": 62.466e9,
    "TRXUSDT": 31.456e9,
    "ZECUSDT": 21.457e9,
    "DOGEUSDT": 12.778e9,
    "LINKUSDT": 9.453e9,
    "ADAUSDT": 8.371e9,
    "NEARUSDT": 6.577e9,
    "XLMUSDT": 6.403e9,
    "BCHUSDT": 5.729e9,
    "LTCUSDT": 4.760e9,
    "UNIUSDT": 4.665e9,
    "AVAXUSDT": 4.299e9,
    "SUIUSDT": 4.215e9,
    "HBARUSDT": 3.657e9,
    "TAOUSDT": 3.071e9,
    "SHIBUSDT": 3.017e9,
    "QNTUSDT": 2.856e9,
    "ENAUSDT": 2.691e9,
    "AAVEUSDT": 2.385e9,
    "WLDUSDT": 2.237e9,
    "PUMPUSDT": 2.197e9,
    "ONDOUSDT": 2.192e9,
    "DOTUSDT": 1.970e9,
    "ASTERUSDT": 1.956e9,
    "PEPEUSDT": 1.890e9,
    "SKYUSDT": 1.766e9,
    "WLFIUSDT": 1.745e9,
    "ICPUSDT": 1.624e9,
    "MORPHOUSDT": 1.609e9,
    "ARBUSDT": 1.305e9,
    "ETCUSDT": 1.262e9,
    "JUPUSDT": 1.043e9,
    "ALGOUSDT": 1.026e9,
    "POLUSDT": 1.017e9,
    "RENDERUSDT": 0.956e9,
    "ATOMUSDT": 0.934e9,
    "INJUSDT": 0.876e9,
    "FILUSDT": 0.861e9,
    "ZROUSDT": 0.813e9,
    "APTUSDT": 0.728e9,
    "CAKEUSDT": 0.717e9,
    "STXUSDT": 0.673e9,
    "ETHFIUSDT": 0.672e9,
    "DASHUSDT": 0.643e9,
    "PYTHUSDT": 0.636e9,
    "VETUSDT": 0.620e9,
}

# Deslizamiento (puntos base) por moneda según la liquidez de su par USDT en Binance (volumen diario promedio de 30 días).
SLIPPAGE_BPS = {
    "BTCUSDT": 5,
    "ETHUSDT": 5,
    "BNBUSDT": 8,
    "XRPUSDT": 5,
    "SOLUSDT": 5,
    "TRXUSDT": 15,
    "ZECUSDT": 5,
    "DOGEUSDT": 8,
    "LINKUSDT": 8,
    "ADAUSDT": 8,
    "NEARUSDT": 5,
    "XLMUSDT": 15,
    "BCHUSDT": 15,
    "LTCUSDT": 8,
    "UNIUSDT": 8,
    "AVAXUSDT": 8,
    "SUIUSDT": 8,
    "HBARUSDT": 15,
    "TAOUSDT": 8,
    "SHIBUSDT": 25,
    "QNTUSDT": 8,
    "ENAUSDT": 8,
    "AAVEUSDT": 15,
    "WLDUSDT": 8,
    "PUMPUSDT": 8,
    "ONDOUSDT": 8,
    "DOTUSDT": 15,
    "ASTERUSDT": 15,
    "PEPEUSDT": 8,
    "SKYUSDT": 25,
    "WLFIUSDT": 25,
    "ICPUSDT": 15,
    "MORPHOUSDT": 25,
    "ARBUSDT": 15,
    "ETCUSDT": 25,
    "JUPUSDT": 25,
    "ALGOUSDT": 25,
    "POLUSDT": 25,
    "RENDERUSDT": 25,
    "ATOMUSDT": 25,
    "INJUSDT": 15,
    "FILUSDT": 15,
    "ZROUSDT": 15,
    "APTUSDT": 15,
    "CAKEUSDT": 25,
    "STXUSDT": 25,
    "ETHFIUSDT": 25,
    "DASHUSDT": 15,
    "PYTHUSDT": 25,
    "VETUSDT": 40,
}

UNIVERSE_SYMBOLS = list(CAPS_USD)            # 50 símbolos, de mayor a menor capitalización
TOP25 = UNIVERSE_SYMBOLS[:25]
TOP50 = UNIVERSE_SYMBOLS[:50]

_RISK = dict(max_drawdown=0.50, action="flag_only")        # solo alerta informativa; la cartera sigue (es pasiva por diseño)
_PARAMS = dict(rebalance_hours=720, cash_buffer=0.005, min_trade_usdt=8.0, min_weight=0.0008)


def _slip(symbols):
    return {s: SLIPPAGE_BPS[s] for s in symbols}


BOTS = [
    dict(
        id="i01_index_cap25", kind="index", name="Índice Top-25 (capitalización)", exchange="binance",
        symbols=TOP25, caps_usd={s: CAPS_USD[s] for s in TOP25}, slippage_map_bps=_slip(TOP25), slippage_bps=10,
        capital_pct=1 / 3, risk_level="medio",
        vol_profile="Mercado amplio: domina BTC/ETH (tope 30 % cada una)",
        differentiator="Cartera pasiva: compra el Top-25 ponderado por capitalización con tope de 30 % y rebalancea cada 30 días. "
                       "Es la referencia 'el mercado'. Comparte monedas con los otros dos índices por diseño.",
        params=dict(weighting="cap", cap_max=0.30, **_PARAMS), risk=_RISK,
    ),
    dict(
        id="i02_index_cap50", kind="index", name="Índice Top-50 (capitalización)", exchange="binance",
        symbols=TOP50, caps_usd={s: CAPS_USD[s] for s in TOP50}, slippage_map_bps=_slip(TOP50), slippage_bps=10,
        capital_pct=1 / 3, risk_level="medio",
        vol_profile="Mercado amplio con cola larga de monedas pequeñas e ilíquidas",
        differentiator="Igual que el Top-25 pero con 50 monedas. OJO: ponderar por capitalización hace que la cola pese muy poco, "
                       "así que se parece mucho al Top-25 (mide cuánto aporta ampliar el universo).",
        params=dict(weighting="cap", cap_max=0.30, **_PARAMS), risk=_RISK,
    ),
    dict(
        id="i03_index_ew25", kind="index", name="Índice Top-25 (igual peso)", exchange="binance",
        symbols=TOP25, slippage_map_bps=_slip(TOP25), slippage_bps=10,
        capital_pct=1 / 3, risk_level="medio",
        vol_profile="Mercado amplio con más peso en monedas medianas (4 % cada una)",
        differentiator="Las mismas 25 monedas que el índice por capitalización pero con 4 % cada una: apuesta más a las pequeñas "
                       "y menos a BTC/ETH. El rebalanceo mensual vende lo que subió y compra lo que bajó (puede ayudar o dañar).",
        params=dict(weighting="equal", **_PARAMS), risk=_RISK,
    ),
]
