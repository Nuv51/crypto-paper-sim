"""Sondeo punto-en-el-tiempo de Binance spot para el backtest V2 (un archivo por año, solo lectura, APIs públicas).

  python scripts/pit_v2.py --years 2019,2020,... --inputs backtest_v2/inputs --out OUT

Para cada año: candidatas = Top-120 por capitalización de la foto de CoinMarketCap anterior al 1 de enero (sin estables ni
tokens de otros exchanges), más USDC/FDUSD (para el bot de estables) y BTC/ETH. Por moneda <M>USDT usa solo datos de Binance
(reutiliza scripts/universe_2025.py): primera vela, velas diarias del año, cierre previo y liquidez de los 30 días previos.
No mira precios del año para decidir quién entra: solo si la moneda existe y cotiza todo el año.
"""
import argparse, json, sys, time
from pathlib import Path
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from universe_2025 import profile, to_ms          # noqa: E402
from make_universe_2025 import EXCLUDE            # noqa: E402

SNAP = {2019: "2018-12-30", 2020: "2019-12-29", 2021: "2020-12-27", 2022: "2021-12-26", 2023: "2022-12-25", 2024: "2023-12-31"}
ALIAS = {"MIOTA": "IOTA", "BCHSV": "BSV", "BCHABC": "BCH", "NANO": "XNO", "YOYOW": "YOYO", "ETHOS": "BQX", "RPX": "RPX"}
MORE_EXCLUDE = {"BUSD", "PAX", "USDK", "HUSD", "SAI", "FTT", "CEL", "BTMX", "UST", "LUNC", "USTC", "WBTC", "RENBTC", "HBTC", "IMBTC",
                "STETH", "TBTC", "EURS", "USDN", "XSGD", "MUSD", "CUSDC", "CDAI", "CETH", "AETH", "YFI_USD"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default="2019,2020,2021,2022,2023,2024")
    ap.add_argument("--inputs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--top", type=int, default=120)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    for y in [int(x) for x in a.years.split(",")]:
        caps = json.loads((Path(a.inputs) / f"caps_cmc_{SNAP[y]}.json").read_text())["caps_usd"]
        cands = []
        for sym in list(caps)[: a.top]:
            if sym in EXCLUDE or sym in MORE_EXCLUDE:
                continue
            cands.append(ALIAS.get(sym, sym))
        for must in ("BTC", "ETH", "USDC", "FDUSD"):
            if must not in cands:
                cands.append(must)
        t0, t1 = to_ms(f"{y}-01-01"), to_ms(f"{y + 1}-01-01")
        res = {}
        for base in cands:
            try:
                res[base] = profile(s, base, t0, t1)
            except Exception as e:
                res[base] = {"status": "ERROR", "error": f"{type(e).__name__}: {e}"[:200]}
            time.sleep(0.15)
        (out / f"binance_pit{y}.json").write_text(json.dumps(res, indent=1))
        ok = sum(1 for v in res.values() if v.get("status") == "OK")
        print(y, f"candidatas {len(cands)} · con datos {ok}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
