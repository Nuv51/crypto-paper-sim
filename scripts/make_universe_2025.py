"""Arma el universo del backtest 2025 COMO SI HOY FUERA 2025-01-01 y escribe config_index_2025.py.

  python scripts/make_universe_2025.py

Entradas (backtest_2025/inputs/):
  binance_pit2025.json            salida de scripts/universe_2025.py (historial, días de 2025, cierre 2024, liquidez de dic-2024)
  caps_cmc_2025-01-01.json        capitalización exacta del 2025-01-01 (CoinMarketCap) para las monedas que aparecían en su Top-20
  caps_coingecko_2026-10-20.json  capitalización de HOY, solo para estimar el resto: cap_2025 ≈ (cap_hoy / precio_hoy) × precio_2024-12-31

Reglas (las mismas del universo en vivo, aplicadas a la fecha de inicio):
  1. historial en Binance spot USDT ≥ 365 días antes del 2025-01-01 (primera vela ≤ 2024-01-01);
  2. con vela diaria en (casi) todo 2025 (≥ 360 de 365), para poder simularlo completo;
  3. sin estables, tokens de fondos, oro tokenizado ni tokens de otros exchanges (los candidatos ya vienen filtrados);
  4. orden por capitalización del 2025-01-01; Top-25 y Top-50 del resultado;
  5. deslizamiento por liquidez de dic-2024: ≥100 M → 5 bps · ≥30 M → 8 · ≥10 M → 15 · ≥3 M → 25 · menos → 40.
Nada aquí mira precios de 2025 para decidir quién entra (solo se exige que existan).
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IN = ROOT / "backtest_2025" / "inputs"
OUT = ROOT / "backtest_2025"
RENAMED_TODAY = {"TON": "GRAM"}           # CoinGecko lista Toncoin como GRAM hoy


def tier(vol: float) -> int:
    return 5 if vol >= 100e6 else 8 if vol >= 30e6 else 15 if vol >= 10e6 else 25 if vol >= 3e6 else 40


def build():
    uni = json.loads((IN / "binance_pit2025.json").read_text())
    cmc = json.loads((IN / "caps_cmc_2025-01-01.json").read_text())["caps_usd"]
    today = json.loads((IN / "caps_coingecko_2026-10-20.json").read_text())
    ranked, excluded = [], []
    for base, v in uni.items():
        if v.get("status") != "OK" or not v.get("close_2024"):
            excluded.append((base, "no cotizaba en Binance spot antes de 2025 o ya no existe", None)); continue
        if v["first_day"] > "2024-01-01":
            excluded.append((base, f"historial < 365 días al 2025-01-01 (listada {v['first_day']})", None)); continue
        if v["days_2025"] < 360:
            excluded.append((base, f"dejó de cotizar o tiene huecos en 2025 ({v['days_2025']} días; última {v['last_day']})", None)); continue
        if base in cmc:
            cap, src = float(cmc[base]), "cmc"
        else:
            cap_now = today.get(base) or today.get(RENAMED_TODAY.get(base, ""))
            if not cap_now:
                excluded.append((base, "sin capitalización actual para estimar su cap de 2025 (fuera del Top-200 de hoy)", None)); continue
            cap, src = cap_now / v["last_close"] * v["close_2024"], "estimada"
        ranked.append(dict(base=base, symbol=base + "USDT", cap=round(cap), cap_source=src, first_day=v["first_day"],
                           vol30=v["vol30_2024"], slippage_bps=tier(v["vol30_2024"])))
    ranked.sort(key=lambda r: -r["cap"])
    return ranked, excluded


def main():
    ranked, excluded = build()
    top50 = ranked[:50]
    meta = dict(as_of="2025-01-01", n_candidates=len(ranked) + len(excluded), top50=top50,
                next_in_line=ranked[50:60], excluded=[dict(base=b, reason=r) for b, r, _ in excluded])
    (OUT / "universe_2025.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    caps = "\n".join(f'    "{r["symbol"]}": {r["cap"] / 1e9:.3f}e9,  # {r["cap_source"]}' for r in top50)
    slip = "\n".join(f'    "{r["symbol"]}": {r["slippage_bps"]},' for r in top50)
    src = (ROOT / "config_index.py").read_text()
    head, rest = src.split("PORTFOLIO_CAPITAL = 30_000.0", 1)
    tail = "def _slip(symbols):" + rest.split("def _slip(symbols):", 1)[1]
    doc = '''"""Índice pasivo — BACKTEST EN FRÍO 2025 (generado por scripts/make_universe_2025.py; no editar a mano).

Mismos tres bots, mismos parámetros y mismas reglas de ejecución que `config_index.py`, pero con el universo y las
capitalizaciones tal como se habrían visto el 2025-01-01 (ver BACKTEST_2025.md). Capitalización: exacta de CoinMarketCap
para las monedas de su Top-20 de ese día; para el resto, estimada como (cap de hoy / precio de hoy) × precio del 2024-12-31
(aproximación: supone el mismo suministro circulante; sobrestima monedas con desbloqueos grandes desde entonces).
"""
'''
    body = f'''
PORTFOLIO_CAPITAL = 30_000.0      # 3 bots × 10,000 USDT FICTICIOS
INTERVAL = "1h"
PORTFOLIO_RISK = dict(max_drawdown=None, cooldown_bars=168)

# Capitalización estimada al 2025-01-01 en USD, de mayor a menor.
CAPS_USD = {{
{caps}
}}

# Deslizamiento (bps) según el volumen diario promedio de los 30 días previos al 2025-01-01.
SLIPPAGE_BPS = {{
{slip}
}}

UNIVERSE_SYMBOLS = list(CAPS_USD)
TOP25 = UNIVERSE_SYMBOLS[:25]
TOP50 = UNIVERSE_SYMBOLS[:50]

_RISK = dict(max_drawdown=0.50, action="flag_only")
_PARAMS = dict(rebalance_hours=720, cash_buffer=0.005, min_trade_usdt=8.0, min_weight=0.0008)


'''
    cfg = doc + body + tail
    (ROOT / "config_index_2025.py").write_text(cfg)
    print(f"{len(ranked)} elegibles, {len(excluded)} excluidas; Top-50 escrito")
    for i, r in enumerate(top50, 1):
        print(i, r["base"], f'{r["cap"]/1e9:.2f}B', r["cap_source"], r["slippage_bps"])


if __name__ == "__main__":
    main()
