"""Observatorio de mercado · FASE 2: anuncios y calendario (listados/retiros en exchanges, reuniones FOMC) + estudio de eventos.

Solo lectura de anuncios públicos. Cada evento se guarda con la hora de PUBLICACIÓN y se deduplica por id; no se reescribe.
CPI de EE. UU. no se incluye: la fuente oficial (BLS) bloquea a GitHub Actions (HTTP 403) y no se inventan fechas.
El estudio de eventos mide el retorno anormal (frente a la mediana de la misma moneda) en [-1,+1] y [+1,+7] días.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

BINANCE_CMS = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
BINANCE_CATALOGS = {"listing": 48, "delisting": 161}          # 48 = nuevos listados (verificado); 161 = retiros (por confirmar)
OKX_ANN = "https://www.okx.com/api/v5/support/announcements"
KUCOIN_ANN = "https://api.kucoin.com/api/v3/announcements"
FED_FOMC = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
# Calendario FOMC (día de la decisión = último día de la reunión) de 2022 a 2026, según los calendarios publicados por la Fed. Se usa siempre
# como base; las fechas que se lean de la página de la Fed solo se agregan si esa lectura reproduce todas las de 2026 (control de cordura).
FOMC_STATIC = [
    "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15", "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14", "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12", "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18", "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09"]
NOT_TICKERS = {"USD", "USDT", "USDC", "BUSD", "FDUSD", "EUR", "TRY", "BRL", "MXN", "ARS", "UTC", "AI", "NFT", "API", "ETF", "DEX", "DAO",
               "THE", "AND", "FOR", "NEW", "ALL", "SPOT", "SEED", "TAG", "PRE", "BTC", "ETH"}
MAX_EVENTS = 5000
MIN_EVENTS_STUDY = 20


def _ms(x) -> Optional[int]:
    try:
        v = int(float(x))
        return v * 1000 if v < 10 ** 11 else v
    except (TypeError, ValueError):
        return None


def extract_symbols(title: str) -> list[str]:
    """Tickers que menciona un titular: '(ABC)' o 'will list ABC'. Conservador: si dudamos, no devolvemos nada."""
    out = []
    for m in re.finditer(r"\(([A-Z0-9]{2,10})\)", title or ""):
        out.append(m.group(1))
    for m in re.finditer(r"(?:[Ll]ist|[Dd]elist|[Rr]emove|[Aa]dd)(?:ing)?\s+(?:the\s+)?([A-Z][A-Z0-9]{1,9})(?=[\s,)(/]|$)", title or ""):
        out.append(m.group(1))
    seen, res = set(), []
    for t in out:
        if t not in seen and t not in NOT_TICKERS:
            seen.add(t)
            res.append(t)
    return res


def _kind(title: str, hint: Optional[str] = None) -> Optional[str]:
    t = (title or "").lower()
    if "delist" in t or "removal" in t or "remove " in t or hint == "delisting":
        return "delisting"
    if "list" in t or hint == "listing":
        return "listing"
    return None


def parse_binance_cms(payload: dict, hint: str) -> list[dict]:
    d = payload.get("data") or {}
    arts = d.get("articles") or [a for c in d.get("catalogs", []) for a in c.get("articles", [])]
    out = []
    for a in arts:
        ts, title = _ms(a.get("releaseDate")), a.get("title", "")
        if ts is None or not a.get("code"):
            continue
        out.append({"id": f"binance:{a['code']}", "exchange": "binance", "kind": _kind(title, hint) or hint, "title": title, "ts_pub": ts,
                    "symbols": extract_symbols(title), "url": f"https://www.binance.com/en/support/announcement/{a['code']}"})
    return out


def parse_okx_announcements(payload: dict, hint: str) -> list[dict]:
    if str(payload.get("code")) != "0":
        raise ValueError(f"OKX code={payload.get('code')} {payload.get('msg')}")
    out = []
    for blk in payload.get("data") or []:
        for a in blk.get("details", []):
            ts, title = _ms(a.get("pTime")), a.get("title", "")
            if ts is None or not a.get("url"):
                continue
            out.append({"id": "okx:" + a["url"].rstrip("/").split("/")[-1], "exchange": "okx", "kind": _kind(title, hint) or hint,
                        "title": title, "ts_pub": ts, "symbols": extract_symbols(title), "url": a["url"]})
    return out


def parse_kucoin_announcements(payload: dict, hint: str) -> list[dict]:
    out = []
    for a in (payload.get("data") or {}).get("items", []):
        ts, title = _ms(a.get("cTime")), a.get("annTitle", "")
        if ts is None or a.get("annId") is None:
            continue
        out.append({"id": f"kucoin:{a['annId']}", "exchange": "kucoin", "kind": _kind(title, hint) or hint, "title": title, "ts_pub": ts,
                    "symbols": extract_symbols(title), "url": a.get("annUrl", "")})
    return out


def _fomc_ts(day: str) -> int:
    """La decisión se publica a las 14:00 hora de Nueva York del último día de la reunión."""
    d = datetime.fromisoformat(day).replace(hour=14, tzinfo=ZoneInfo("America/New_York"))
    return int(d.astimezone(timezone.utc).timestamp() * 1000)


MONTHS = {m: i + 1 for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August", "September",
                                          "October", "November", "December"])}


def parse_fomc_html(html: str) -> list[str]:
    """Fechas de decisión (último día de cada reunión) desde la página de calendarios de la Fed. Devuelve [] si el formato no se reconoce."""
    out = []
    for blk in re.split(r"(?=\b(20\d\d)\s+FOMC\s+Meetings)", html):
        m = re.match(r"(20\d\d)\s+FOMC\s+Meetings", blk)
        if not m:
            continue
        year = int(m.group(1))
        for mo, days in re.findall(r"fomc-meeting__month[^>]*>\s*(?:<strong>)?\s*([A-Z][a-z]+)\s*(?:</strong>)?\s*</div>\s*"
                                   r"<div[^>]*fomc-meeting__date[^>]*>\s*([0-9]{1,2}(?:\s*-\s*[0-9]{1,2})?)", blk):
            if mo not in MONTHS:
                continue
            last = int(re.split(r"\s*-\s*", days)[-1])
            out.append(f"{year}-{MONTHS[mo]:02d}-{last:02d}")
    return sorted(set(out))


def fomc_events(html: Optional[str] = None) -> list[dict]:
    """Calendario base (2022-2026, fijo) + fechas FUTURAS (2027 en adelante) leídas de la página de la Fed, solo si la lectura reproduce
    las 8 reuniones de 2026 (control de cordura). Años que ya están en el calendario base no se toman de la página: ahí hay
    otras fechas con el mismo formato (p. ej. el discurso de Jackson Hole) que no son reuniones."""
    days = set(FOMC_STATIC)
    parsed = parse_fomc_html(html) if html else []
    if set(d for d in FOMC_STATIC if d.startswith("2026")) <= set(parsed):
        days |= {d for d in parsed if d >= "2027-01-01"}
    return [{"id": f"fomc:{d}", "exchange": "fed", "kind": "fomc", "title": f"Decisión FOMC {d}", "ts_pub": _fomc_ts(d), "symbols": ["BTC"],
             "url": FED_FOMC} for d in sorted(days)]


def merge_events(store: list[dict], new: list[dict], cap: int = MAX_EVENTS) -> tuple[list[dict], int]:
    """Agrega los eventos nuevos (por id; un evento ya guardado no se reescribe). Devuelve (lista, cuántos se agregaron)."""
    have = {e["id"] for e in store}
    add = [e for e in new if e["id"] not in have]
    merged = sorted(store + add, key=lambda e: (e["ts_pub"], e["id"]))
    return merged[-cap:], len(add)


# ======================================================================================
# Estudio de eventos
# ======================================================================================
def _ret(close: np.ndarray, i0: int, i1: int) -> float:
    if i0 < 0 or i1 >= len(close) or not (np.isfinite(close[i0]) and np.isfinite(close[i1])) or close[i0] <= 0:
        return float("nan")
    return float(np.log(close[i1] / close[i0]))


def event_study(events: list[dict], closes: dict[str, pd.Series], windows=((-1, 1), (1, 7)), n_perm: int = 2000, seed: int = 20261110) -> dict:
    """Retorno anormal por ventana: de cierre(t+a) a cierre(t+b), con t = día UTC de la publicación (cierres diarios) para eventos de UN tipo.
    Anormal = retorno de la ventana − mediana de la misma moneda en todos los días con datos. Prueba: fechas al azar de la misma moneda."""
    rng = np.random.default_rng(seed)
    res = {"n_eventos": len(events), "ventanas": {}}
    for (a, b) in windows:
        recs = []                                              # (fecha, abnormal, símbolo, serie, base)
        sin_precio = 0
        for e in events:
            for sym in e.get("symbols") or []:
                ser = closes.get(sym)
                if ser is None:
                    ser = closes.get(sym + "USDT")
                if ser is None or len(ser) < 60:
                    sin_precio += 1
                    continue
                arr = ser.to_numpy(dtype=float)
                day = pd.Timestamp(e["ts_pub"], unit="ms").normalize()
                if day not in ser.index:
                    sin_precio += 1
                    continue
                i = int(ser.index.get_loc(day))
                r = _ret(arr, i + a, i + b)                    # de cierre(t+a) a cierre(t+b); t = día UTC de la publicación
                if not np.isfinite(r):
                    sin_precio += 1
                    continue
                width = b - a
                allr = np.log(arr[width:] / arr[:-width]) if width > 0 else np.array([])
                allr = allr[np.isfinite(allr)]
                if len(allr) < 30:
                    sin_precio += 1
                    continue
                base = float(np.median(allr))
                recs.append((day, r - base, sym, allr, base, e["ts_pub"]))
        w = {"n": len(recs), "sin_precio": sin_precio, "mediana": None, "p": None, "mismo_signo_mitades": None}
        if recs:
            stat = float(np.median([x[1] for x in recs]))
            w["mediana"] = stat
            w["pct_positivo"] = float(np.mean([x[1] > 0 for x in recs]))
            hits = 0
            for _ in range(n_perm):
                draw = [rng.choice(x[3]) - x[4] for x in recs]
                hits += abs(float(np.median(draw))) >= abs(stat)
            w["p"] = float((1 + hits) / (1 + n_perm))
            recs.sort(key=lambda x: x[5])
            h = len(recs) // 2
            if h >= 3:
                s1, s2 = np.median([x[1] for x in recs[:h]]), np.median([x[1] for x in recs[h:]])
                w["mismo_signo_mitades"] = bool(np.sign(s1) == np.sign(s2) != 0)
        res["ventanas"][f"{a:+d}_{b:+d}"] = w
    return res


def study_verdict(w: dict) -> tuple[str, str]:
    """Criterio del pre-registro: p < 0.01, ≥ 20 eventos con precio y mismo signo en las dos mitades."""
    if w["n"] < MIN_EVENTS_STUDY:
        return "sin veredicto", f"muestra pequeña ({w['n']} eventos con precio; mínimo {MIN_EVENTS_STUDY})"
    if w["p"] is not None and w["p"] < 0.01 and w["mismo_signo_mitades"]:
        return "con evidencia", "cumple los criterios"
    return "sin evidencia suficiente", f"p={w['p']:.3f}" + ("" if w["mismo_signo_mitades"] else "; signo distinto en las mitades")
