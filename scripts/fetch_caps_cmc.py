"""Captura las capitalizaciones de CoinMarketCap (páginas /historical/<fecha>/) para fijar el universo de cada año del backtest V2.

  python scripts/fetch_caps_cmc.py --dates 2018-12-30,2019-12-29,... --out DIR

Usa la foto semanal (domingo) más reciente ESTRICTAMENTE ANTERIOR al 1 de enero de cada año, para no mirar nada posterior al inicio.
Escribe DIR/caps_cmc_<fecha>.json = {"date", "n", "caps_usd": {SIMBOLO: cap}, "rank": {SIMBOLO: n}, "names": {SIMBOLO: nombre}}
y imprime un resumen (si la estructura de la página cambia, imprime las rutas para ajustar el lector; nunca inventa datos).
"""
import argparse, json, re, sys, time
from pathlib import Path
import requests

S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (compatible; research; +https://github.com)"


def find_lists(node, path=""):
    """Todas las listas de dicts que parecen listados de monedas: (ruta, lista)."""
    if isinstance(node, list):
        if node and all(isinstance(x, dict) for x in node[:5]) and any("symbol" in x for x in node[:5]):
            yield path, node
        for i, x in enumerate(node[:3]):
            yield from find_lists(x, f"{path}[{i}]")
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from find_lists(v, f"{path}.{k}")


def mcap(item):
    for k in ("marketCap", "market_cap", "mcap"):
        if isinstance(item.get(k), (int, float)):
            return float(item[k])
    q = item.get("quote") or item.get("quotes")
    if isinstance(q, dict):
        q = q.get("USD") or next(iter(q.values()), None)
        if isinstance(q, dict):
            for k in ("marketCap", "market_cap"):
                if isinstance(q.get(k), (int, float)):
                    return float(q[k])
    if isinstance(q, list):
        for e in q:
            if isinstance(e, dict) and e.get("name", "USD") == "USD":
                for k in ("marketCap", "market_cap"):
                    if isinstance(e.get(k), (int, float)):
                        return float(e[k])
    return None


def parse(html):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None, "sin __NEXT_DATA__"
    data = json.loads(m.group(1))
    best, info = None, []
    for path, lst in find_lists(data):
        caps = [mcap(x) for x in lst]
        info.append((path, len(lst), sum(c is not None for c in caps), sorted(lst[0].keys())[:25]))
        if sum(c is not None for c in caps) >= 50 and (best is None or len(lst) > len(best[1])):
            best = (path, lst)
    if not best:
        return None, "listas encontradas: " + json.dumps(info)[:1500]
    return best, "ruta " + best[0]


def parse_table(html):
    """Respaldo: la tabla HTML de la página (Top-100 del día): símbolo, nombre y capitalización por fila."""
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        sym = re.search(r'cmc-table__cell--sort-by__symbol"[^>]*><div[^>]*>([^<]+)</div>', tr)
        cap = re.search(r'cmc-table__cell--sort-by__market-cap"[^>]*><div[^>]*>\$?([\d,\.]+)</div>', tr)
        nm = re.search(r'cmc-table__column-name--name[^>]*>([^<]+)</a>', tr)
        if sym and cap:
            rows.append(dict(symbol=sym.group(1).strip(), name=nm.group(1).strip() if nm else "", marketCap=float(cap.group(1).replace(",", ""))))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    ok = True
    for d in a.dates.split(","):
        url = f"https://coinmarketcap.com/historical/{d.replace('-', '')}/"
        r = S.get(url, timeout=60)
        if r.status_code != 200:
            print(d, "HTTP", r.status_code); ok = False; continue
        best, msg = parse(r.text)
        if not best:
            tab = parse_table(r.text)
            if len(tab) >= 50:
                best, msg = ("tabla HTML", tab), "tabla HTML"
            else:
                print(d, "no pude leer:", msg, "| tabla:", len(tab)); ok = False; continue
        rows = []
        for x in best[1]:
            c = mcap(x)
            if c and x.get("symbol"):
                rows.append((x.get("cmcRank") or x.get("rank") or len(rows) + 1, str(x["symbol"]).upper(), x.get("name", ""), c))
        rows.sort(key=lambda t: -t[3])
        caps, rank, names = {}, {}, {}
        for i, (_, sym, nm, c) in enumerate(rows, 1):
            if sym not in caps:                       # símbolos repetidos: se conserva el de mayor capitalización
                caps[sym], rank[sym], names[sym] = c, i, nm
        (out / f"caps_cmc_{d}.json").write_text(json.dumps({"date": d, "source": url, "n": len(caps), "caps_usd": caps, "rank": rank, "names": names}, ensure_ascii=False))
        top = list(caps)[:12]
        print(d, msg, "·", len(caps), "monedas · top:", ", ".join(f"{s}:{caps[s]/1e9:.1f}B" for s in top), flush=True)
        time.sleep(1.5)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
