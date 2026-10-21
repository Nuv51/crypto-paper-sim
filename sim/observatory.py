"""Observatorio de spreads: ¿dónde (y cuántas veces) un spread entre exchanges supera de verdad los costos?

QUÉ ES
  Una herramienta de MEDICIÓN, no un bot. No opera ni simula operaciones: toma fotos del mejor precio de compra/venta
  de cada moneda en Bitso (mercado USDT), Binance y KuCoin, calcula el spread bruto y el neto de comisiones y
  slippage de CADA ruta (comprar en A al ask, vender en B al bid), y acumula estadísticas durante semanas.
  Sirve para decidir con datos qué monedas/rutas merecen un bot de arbitraje, antes de construirlo.

QUÉ MIDE (por moneda y ruta, p. ej. "XRP|bitso>binance")
  * cuántas veces el neto fue > 0 y cuántas ≥ el umbral (0.30 % por defecto, el mismo del bot #10);
  * distribución del neto (histograma), el mejor neto y la profundidad disponible en la punta del libro;
  * PERSISTENCIA: de las veces que hubo oportunidad ≥ umbral, cuántas seguían ahí ~20 s después. Una oportunidad
    que desaparece en un segundo no la captura un bot sin latencia ultrabaja; una que dura decenas de segundos, sí;
  * cota superior de ganancia diaria si se hubiera capturado cada oportunidad (con tope de tamaño);
  * rutas de CONTROL (Binance ↔ KuCoin, sin Bitso): si Bitso no muestra más oportunidades que ellas, el "nicho
    Bitso" no existe y la idea se cae;
  * la prima del peso: precio implícito en USDT de cada moneda vía Bitso MXN frente al precio de Binance.

LÍMITES (léelos antes de sacar conclusiones)
  * Fotos cada ~20 s durante ~2 min por corrida horaria: NO es el flujo continuo del mercado. Estima frecuencia y
    persistencia, no la carrera de latencia contra bots profesionales.
  * El neto usa comisiones taker base (Bitso USDT 0.36 %, Binance y KuCoin 0.10 %) y 5 bps de slippage por pata.
    Las monedas KuCoin Clase B/C pagan más (0.16–0.24 % en el nivel base): el neto de esas rutas está sobreestimado.
  * Asume fondos pre-posicionados en cada exchange: no incluye el costo de rebalancear (retiros, red, tiempo).
  * Un mismo ticker puede ser proyectos distintos en exchanges distintos: spreads brutos > 20 % se descartan como
    sospechosos y se cuentan aparte.
  * Mientras el periodo observado sea corto no hay veredicto: regla del proyecto, mínimo ~30 días.

REGLA DE LA PRUEBA
  Los parámetros (umbral, slippage, tope de tamaño) quedan guardados en el estado. Si cambian, la corrida se niega
  a continuar (hay que empezar de cero): no se afinan parámetros a mitad de una medición.

Todo es de solo lectura sobre APIs públicas: sin llaves, sin órdenes, sin dinero.
"""
from __future__ import annotations

import math
import time
from typing import Callable, Optional

import requests

from .data import BITSO, KUCOIN_SPOT, _http_json
from .exchanges import EXCHANGES

# ======================================================================================
# Parámetros y constantes
# ======================================================================================
VENUES = ("bitso", "binance", "kucoin")
FEE_KEY = {"bitso": "bitso_usdt", "binance": "binance", "kucoin": "kucoin"}   # perfiles de sim/exchanges.py
BINANCE_BASES = ("https://data-api.binance.vision", "https://api.binance.com")

DEFAULT_PARAMS = dict(
    threshold=0.003,        # neto mínimo para contar como "oportunidad" (igual que el bot #10)
    slip_bps=5.0,           # slippage adverso por pata
    cap_usdt=3000.0,        # tope de tamaño por oportunidad (30 % de 10,000 USDT, como el bot #10)
    max_spread=0.05,        # spread interno (ask/bid - 1) mayor a esto = libro ilíquido, se ignora
    max_gross=0.20,         # bruto mayor a esto = casi seguro tickers distintos, se descarta como sospechoso
    event_log=300,          # cuántas oportunidades netas > 0 se guardan en el registro circular
    verdict_days=30,        # días mínimos antes de dar un veredicto
    mxn_gap_flag=0.005,     # prima del peso que se considera "notable" (0.5 %)
)

# Histograma del neto: [-2 %, +1 %] en pasos de 0.25 %; el primer y el último casillero acumulan las colas.
HIST_LO, HIST_STEP, HIST_BINS = -0.02, 0.0025, 13
DAY_MS = 86_400_000


def hist_index(net: float) -> int:
    return max(0, min(HIST_BINS - 1, int(math.floor((net - HIST_LO) / HIST_STEP))))


def hist_labels() -> list[str]:
    edges = [HIST_LO + i * HIST_STEP for i in range(HIST_BINS)]
    out = [f"< {edges[1]:+.2%}"]
    out += [f"{edges[i]:+.2%} a {edges[i + 1]:+.2%}" for i in range(1, HIST_BINS - 1)]
    out.append(f"≥ {edges[-1]:+.2%}")
    return out


def taker(venue: str) -> float:
    return EXCHANGES[FEE_KEY[venue]].taker


NAN = float("nan")


def _f(x) -> float:
    try:
        v = float(x)
        return v if math.isfinite(v) else NAN
    except (TypeError, ValueError):
        return NAN


def _ok(*vals: float) -> bool:
    return all(isinstance(v, (int, float)) and math.isfinite(v) for v in vals)


# Una cotización es una lista [bid, ask, bid_qty, ask_qty]; las cantidades pueden ser NaN (desconocidas).
def _quote(bid, ask, bq=NAN, aq=NAN) -> Optional[list]:
    b, a = _f(bid), _f(ask)
    if not (_ok(b, a) and b > 0 and a > 0 and b <= a):
        return None                                               # sin precio, libro cruzado o mercado detenido
    return [b, a, _f(bq), _f(aq)]


# ======================================================================================
# Lectura de APIs públicas (parsers puros + recolectores)
# ======================================================================================
def parse_bitso_tickers(payload: dict) -> tuple[dict, dict, Optional[float]]:
    """GET /v3/ticker/ (todos los libros) -> (cotizaciones USDT por moneda, punto medio MXN por moneda, USDT/MXN).
    Libros: 'xrp_usdt' (cotización USDT), 'xrp_mxn' (pesos), 'usdt_mxn' (el tipo de cambio de la stablecoin)."""
    usdt: dict[str, list] = {}
    mxn_mid: dict[str, float] = {}
    usdt_mxn: Optional[float] = None
    for r in payload.get("payload") or []:
        book = str(r.get("book", "")).lower()
        if "_" not in book:
            continue
        base, quote = book.split("_", 1)
        q = _quote(r.get("bid"), r.get("ask"))
        if q is None:
            continue
        if quote == "usdt":
            usdt[base.upper()] = q
        elif quote == "mxn":
            if base == "usdt":
                usdt_mxn = (q[0] + q[1]) / 2
            else:
                mxn_mid[base.upper()] = (q[0] + q[1]) / 2
    return usdt, mxn_mid, usdt_mxn


def parse_binance_book_tickers(rows: list) -> dict[str, list]:
    """GET /api/v3/ticker/bookTicker (todos los símbolos) -> {moneda: cotización} para los pares *USDT."""
    out: dict[str, list] = {}
    for r in rows or []:
        sym = str(r.get("symbol", ""))
        if not sym.endswith("USDT") or len(sym) <= 4:
            continue
        q = _quote(r.get("bidPrice"), r.get("askPrice"), r.get("bidQty"), r.get("askQty"))
        if q:
            out[sym[:-4]] = q
    return out


def parse_kucoin_all_tickers(payload: dict) -> dict[str, list]:
    """GET /api/v1/market/allTickers -> {moneda: cotización} para los pares *-USDT (sin tamaños: se piden aparte)."""
    out: dict[str, list] = {}
    for r in ((payload.get("data") or {}).get("ticker")) or []:
        sym = str(r.get("symbol", ""))
        if not sym.endswith("-USDT"):
            continue
        q = _quote(r.get("buy"), r.get("sell"))
        if q:
            out[sym.split("-")[0]] = q
    return out


class LiveFetchers:
    """Recolectores reales (APIs públicas, sin llaves). Cada método puede lanzar excepción; quien lo llama decide."""

    def __init__(self, timeout: float = 15.0, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.timeout = timeout

    def bitso(self):
        return parse_bitso_tickers(_http_json(self.session, BITSO + "/v3/ticker/", None, 2, self.timeout))

    def binance(self) -> dict:
        last: Optional[Exception] = None
        for base in BINANCE_BASES:
            try:
                rows = _http_json(self.session, base + "/api/v3/ticker/bookTicker", None, 2, self.timeout)
                return parse_binance_book_tickers(rows)
            except Exception as e:                                # 451 por región, red caída, etc.: prueba el respaldo
                last = e
        raise RuntimeError(f"Binance bookTicker no respondió: {last}")

    def kucoin(self) -> dict:
        return parse_kucoin_all_tickers(_http_json(self.session, KUCOIN_SPOT + "/api/v1/market/allTickers", None, 2, self.timeout))

    def top_size(self, venue: str, asset: str) -> tuple[float, float]:
        """(cantidad en la punta de compra, cantidad en la punta de venta) de UN par; solo para oportunidades."""
        if venue == "bitso":
            ob = _http_json(self.session, BITSO + "/v3/order_book/", {"book": f"{asset.lower()}_usdt", "aggregate": "true"},
                            2, self.timeout)["payload"]
            return _f(ob["bids"][0]["amount"]), _f(ob["asks"][0]["amount"])
        if venue == "kucoin":
            d = _http_json(self.session, KUCOIN_SPOT + "/api/v1/market/orderbook/level1", {"symbol": f"{asset}-USDT"},
                           2, self.timeout)["data"]
            return _f(d["bestBidSize"]), _f(d["bestAskSize"])
        if venue == "binance":
            for base in BINANCE_BASES:
                try:
                    t = _http_json(self.session, base + "/api/v3/ticker/bookTicker", {"symbol": f"{asset}USDT"}, 2, self.timeout)
                    return _f(t["bidQty"]), _f(t["askQty"])
                except Exception:
                    continue
        raise RuntimeError(f"sin tamaños para {venue}/{asset}")


# ======================================================================================
# Una foto del mercado y su evaluación
# ======================================================================================
def take_snapshot(f, ts_ms: Optional[int] = None) -> Optional[dict]:
    """Junta las cotizaciones de las tres casas. Sin Bitso, o sin ninguna de las otras dos, no hay nada que comparar
    y devuelve None. Solo se consideran las monedas listadas en Bitso (comparación pareja con las rutas de control)."""
    try:
        bitso_usdt, mxn_mid, usdt_mxn = f.bitso()
    except Exception:
        return None
    others: dict[str, dict] = {}
    for v in ("binance", "kucoin"):
        try:
            others[v] = getattr(f, v)()
        except Exception:
            others[v] = {}
    if not bitso_usdt or not (others["binance"] or others["kucoin"]):
        return None
    quotes: dict[str, dict[str, list]] = {}
    for asset, bq in bitso_usdt.items():
        d = {"bitso": bq}
        for v, book in others.items():
            if asset in book:
                d[v] = book[asset]
        if len(d) >= 2:
            quotes[asset] = d
    gaps: dict[str, float] = {}
    if usdt_mxn:
        for asset, mid in mxn_mid.items():
            ref = quotes.get(asset, {}).get("binance") or quotes.get(asset, {}).get("kucoin")
            if ref:
                gaps[asset] = (mid / usdt_mxn) / ((ref[0] + ref[1]) / 2) - 1.0
    return {"ts": ts_ms if ts_ms is not None else int(time.time() * 1000), "quotes": quotes, "mxn_gap": gaps}


def evaluate_snapshot(snap: dict, params: dict, top_size: Optional[Callable[[str, str], tuple]] = None,
                      max_enrich: int = 12) -> tuple[list[dict], int]:
    """Filas por (moneda, ruta) con spread bruto y neto. Devuelve (filas, nº de descartadas como sospechosas).
    `top_size` (opcional) completa los tamaños de punta de las rutas con neto > 0 cuando la casa no los publica."""
    slip = params["slip_bps"] / 1e4
    rows: list[dict] = []
    suspicious = 0
    for asset, q in snap["quotes"].items():
        venues = [v for v, c in q.items() if c[1] / c[0] - 1.0 <= params["max_spread"]]   # fuera libros ilíquidos
        for a in venues:                                          # compra en `a` (ask)
            for b in venues:                                      # vende en `b` (bid)
                if a == b:
                    continue
                gross = q[b][0] / q[a][1] - 1.0
                if abs(gross) > params["max_gross"]:
                    suspicious += 1
                    continue
                net = gross - taker(a) - taker(b) - 2 * slip
                rows.append({"asset": asset, "route": f"{a}>{b}", "buy": a, "sell": b, "gross": gross, "net": net,
                             "control": "bitso" not in (a, b), "bq": q[b][2], "aq": q[a][3]})
    enriched = 0
    for r in sorted(rows, key=lambda x: -x["net"]):               # tamaños solo donde importa
        if r["net"] <= 0 or enriched >= max_enrich or top_size is None:
            break
        if not (_ok(r["bq"]) and _ok(r["aq"])):
            enriched += 1
            for venue, key, idx in ((r["sell"], "bq", 0), (r["buy"], "aq", 1)):
                if not _ok(r[key]):
                    try:
                        r[key] = top_size(venue, r["asset"])[idx]
                    except Exception:
                        pass
    for r in rows:
        q = snap["quotes"][r["asset"]]
        legs = [x for x in (r["aq"] * q[r["buy"]][1], r["bq"] * q[r["sell"]][0]) if _ok(x) and x > 0]
        r["depth"] = min(legs) if len(legs) == 2 else NAN         # profundidad en USDT: la menor de las dos puntas
    return rows, suspicious


# ======================================================================================
# Estadísticas acumuladas (tamaño constante, sin importar cuánto dure la medición)
# ======================================================================================
def new_state(params: Optional[dict] = None, now_ms: Optional[int] = None) -> dict:
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    return {"version": 1, "params": dict(params or DEFAULT_PARAMS), "since_ms": now, "last_ms": now, "runs": 0,
            "snapshots": 0, "failed_snapshots": 0, "suspicious": 0, "routes": {}, "assets": {}, "events": []}


def _route_stats() -> dict:
    return {"n": 0, "n_pos": 0, "n_thr": 0, "sum_gross": 0.0, "sum_net": 0.0, "max_net": None, "max_gross": None,
            "hist": [0] * HIST_BINS, "persist_n": 0, "persist_hit": 0, "thr_depth_known": 0, "thr_depth_sum": 0.0,
            "pnl_ub": 0.0}


def update_stats(state: dict, snap: dict, rows: list[dict], suspicious: int, prev_thr: set) -> set:
    """Suma una foto al estado. `prev_thr` = rutas que estaban ≥ umbral en la foto anterior de ESTA corrida (para la
    persistencia). Devuelve el conjunto de rutas ≥ umbral de esta foto."""
    p = state["params"]
    thr = p["threshold"]
    now_thr: set = set()
    state["snapshots"] += 1
    state["last_ms"] = max(state["last_ms"], snap["ts"])
    state["suspicious"] += suspicious
    for r in rows:
        key = f"{r['asset']}|{r['route']}"
        s = state["routes"].setdefault(key, _route_stats())
        s["n"] += 1
        s["sum_gross"] += r["gross"]
        s["sum_net"] += r["net"]
        s["max_net"] = r["net"] if s["max_net"] is None else max(s["max_net"], r["net"])
        s["max_gross"] = r["gross"] if s["max_gross"] is None else max(s["max_gross"], r["gross"])
        s["hist"][hist_index(r["net"])] += 1
        if key in prev_thr:                                       # ¿la oportunidad de hace ~20 s sigue ahí?
            s["persist_n"] += 1
            s["persist_hit"] += 1 if r["net"] >= thr else 0
        if r["net"] > 0:
            s["n_pos"] += 1
            state["events"].append({"ts": snap["ts"], "asset": r["asset"], "route": r["route"], "gross": round(r["gross"], 5),
                                    "net": round(r["net"], 5), "depth": None if not _ok(r["depth"]) else round(r["depth"], 1)})
        if r["net"] >= thr:
            now_thr.add(key)
            s["n_thr"] += 1
            if _ok(r["depth"]):
                s["thr_depth_known"] += 1
                s["thr_depth_sum"] += r["depth"]
                s["pnl_ub"] += min(r["depth"], p["cap_usdt"]) * r["net"]   # tamaño desconocido = no se cuenta (conservador)
    del state["events"][:-p["event_log"]]
    for asset, gap in snap["mxn_gap"].items():
        a = state["assets"].setdefault(asset, {"gap_n": 0, "gap_sum": 0.0, "gap_abs_max": 0.0, "gap_flag": 0})
        a["gap_n"] += 1
        a["gap_sum"] += gap
        a["gap_abs_max"] = max(a["gap_abs_max"], abs(gap))
        a["gap_flag"] += 1 if abs(gap) >= p["mxn_gap_flag"] else 0
    return now_thr


def observe(state: dict, fetchers, snapshots: int = 6, interval_s: float = 20.0,
            sleep: Callable[[float], None] = time.sleep, clock: Callable[[], int] = lambda: int(time.time() * 1000)) -> int:
    """Una corrida: `snapshots` fotos separadas por `interval_s`. Devuelve cuántas fotos fueron buenas."""
    good, prev_thr = 0, set()
    state["runs"] += 1
    for i in range(snapshots):
        if i:
            sleep(interval_s)
        snap = take_snapshot(fetchers, clock())
        if snap is None:
            state["failed_snapshots"] += 1
            prev_thr = set()
            continue
        rows, susp = evaluate_snapshot(snap, state["params"], getattr(fetchers, "top_size", None))
        prev_thr = update_stats(state, snap, rows, susp, prev_thr)
        good += 1
    return good


# ======================================================================================
# Resumen legible
# ======================================================================================
def summarize(state: dict) -> dict:
    p = state["params"]
    days = max((state["last_ms"] - state["since_ms"]) / DAY_MS, 0.0)
    rows = []
    for key, s in state["routes"].items():
        asset, route = key.split("|")
        n = s["n"]
        rows.append({
            "asset": asset, "route": route, "control": "bitso" not in route.split(">"),
            "n": n, "mean_gross": s["sum_gross"] / n, "mean_net": s["sum_net"] / n, "max_net": s["max_net"],
            "pct_pos": s["n_pos"] / n, "pct_thr": s["n_thr"] / n, "n_thr": s["n_thr"],
            "persistence": (s["persist_hit"] / s["persist_n"]) if s["persist_n"] else None, "persist_n": s["persist_n"],
            "mean_depth_thr": (s["thr_depth_sum"] / s["thr_depth_known"]) if s["thr_depth_known"] else None,
            "pnl_ub_per_day": (s["pnl_ub"] / days) if days >= 1 else None,
            "hist": s["hist"]})
    rows.sort(key=lambda r: (-r["pct_thr"], -r["pct_pos"], -(r["max_net"] or -1)))

    def group(control: bool) -> dict:
        g = [r for r in rows if r["control"] == control]
        n = sum(r["n"] for r in g)
        return {"obs": n, "pct_pos": (sum(r["pct_pos"] * r["n"] for r in g) / n) if n else None,
                "pct_thr": (sum(r["pct_thr"] * r["n"] for r in g) / n) if n else None}

    gaps = sorted(({"asset": a, "n": v["gap_n"], "mean": v["gap_sum"] / v["gap_n"], "abs_max": v["gap_abs_max"],
                    "pct_flag": v["gap_flag"] / v["gap_n"]} for a, v in state["assets"].items() if v["gap_n"]),
                  key=lambda g: -g["abs_max"])
    enough = days >= p["verdict_days"]
    return {"since_ms": state["since_ms"], "last_ms": state["last_ms"], "days": days, "runs": state["runs"],
            "snapshots": state["snapshots"], "failed_snapshots": state["failed_snapshots"],
            "suspicious": state["suspicious"], "params": p, "bitso": group(False), "control": group(True),
            "routes": rows, "mxn_gaps": gaps, "hist_labels": hist_labels(), "events": state["events"][-30:],
            "verdict": ("Hay suficiente muestra: revisa el cuadro por ruta." if enough else
                        f"Sin veredicto: {days:.1f} de {p['verdict_days']} días observados. Una foto no es evidencia.")}


def render_markdown(summary: dict, top: int = 12) -> str:
    pc = lambda v, d=2: "—" if v is None else f"{v:.{d}%}"
    out = [f"**Observatorio de spreads** · {summary['days']:.1f} días · {summary['snapshots']} fotos "
           f"({summary['failed_snapshots']} fallidas) · {summary['suspicious']} descartadas por sospechosas", "",
           summary["verdict"], "",
           f"Bitso: neto>0 en {pc(summary['bitso']['pct_pos'])} · ≥umbral en {pc(summary['bitso']['pct_thr'])} "
           f"({summary['bitso']['obs']:,} obs.)  |  Control (sin Bitso): neto>0 en {pc(summary['control']['pct_pos'])} · "
           f"≥umbral en {pc(summary['control']['pct_thr'])} ({summary['control']['obs']:,} obs.)", "",
           "| Moneda | Ruta | Obs. | Bruto medio | Neto medio | Mejor neto | % ≥ umbral | Persistencia | Prof. media (USDT) |",
           "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in summary["routes"][:top]:
        depth = "—" if r["mean_depth_thr"] is None else f"{r['mean_depth_thr']:,.0f}"
        out.append(f"| {r['asset']} | {r['route']}{' (control)' if r['control'] else ''} | {r['n']:,} | {pc(r['mean_gross'])} | "
                   f"{pc(r['mean_net'])} | {pc(r['max_net'])} | {pc(r['pct_thr'])} | {pc(r['persistence'], 0)} | {depth} |")
    if summary["mxn_gaps"]:
        out += ["", "Prima del peso (precio implícito vía Bitso MXN vs Binance), mayores desvíos:", ""]
        out += [f"- {g['asset']}: media {g['mean']:+.2%}, máx. {g['abs_max']:.2%}, ≥{summary['params']['mxn_gap_flag']:.1%} en {pc(g['pct_flag'], 0)} de las fotos"
                for g in summary["mxn_gaps"][:5]]
    out += ["", "_Estimación con fotos cada ~20 s, no el flujo continuo; no incluye costos de rebalanceo. Medición, no garantía._"]
    return "\n".join(out)
