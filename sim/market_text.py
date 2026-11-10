"""Observatorio de mercado · FASE 3: noticias y redes (RSS de medios cripto, Reddit por RSS, Stocktwits público).

Solo lectura de fuentes públicas. X/Twitter (API de pago) y los grupos privados de Telegram quedan fuera: no hay acceso legítimo.
Se guarda el titular CRUDO (fuente, título, enlace, hora de publicación y hora en que lo VIMOS) para poder re-puntuar con otro método
sin perder nada; el puntaje lleva la versión del método. La evaluación usa la hora en que lo vimos (no la que declara el feed),
para que un feed con fechas atrasadas no meta información del futuro.

Puntaje por defecto (determinista y sin costo): léxico de tono con términos cripto y negación simple. Es una línea base TOSCA: no
entiende ironía, sarcasmo ni contexto. Un modelo de lenguaje puede puntuar los mismos titulares como segunda columna (otro módulo, con llave
secreta); nunca reemplaza ni se mezcla con este.
"""
from __future__ import annotations

import hashlib
import html
import re
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Optional

import numpy as np
import pandas as pd

LEXICON_VERSION = "lex-v1"
MAX_XML_BYTES = 3_000_000
MAX_ITEMS = 12_000

FEEDS = {                                   # fuente → URL (todas respondieron 200 desde GitHub Actions)
    "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "cointelegraph": "https://cointelegraph.com/rss",
    "decrypt": "https://decrypt.co/feed",
    "theblock": "https://www.theblock.co/rss.xml",
    "bitcoinmagazine": "https://bitcoinmagazine.com/.rss/full/",
    "cryptoslate": "https://cryptoslate.com/feed/",
    "reddit_CryptoCurrency": "https://www.reddit.com/r/CryptoCurrency/new/.rss?limit=50",
    "reddit_Bitcoin": "https://www.reddit.com/r/Bitcoin/new/.rss?limit=50",
    "reddit_ethereum": "https://www.reddit.com/r/ethereum/new/.rss?limit=50",
}
STOCKTWITS = {"BTC": "https://api.stocktwits.com/api/2/streams/symbol/BTC.X.json", "ETH": "https://api.stocktwits.com/api/2/streams/symbol/ETH.X.json"}

POS = {"surge": 2, "surges": 2, "soar": 2, "soars": 2, "rally": 2, "rallies": 2, "jump": 1, "jumps": 1, "gain": 1, "gains": 1, "rise": 1, "rises": 1,
       "rebound": 1, "recover": 1, "recovery": 1, "bullish": 2, "breakout": 1, "ath": 2, "record": 1, "approval": 2, "approved": 2, "approves": 2,
       "adopt": 1, "adoption": 1, "inflow": 1, "inflows": 1, "accumulate": 1, "accumulation": 1, "upgrade": 1, "partnership": 1, "launch": 1,
       "launches": 1, "etf": 0.5, "buy": 0.5, "buys": 0.5, "boost": 1, "optimism": 1, "optimistic": 1, "milestone": 1, "outperform": 1,
       "support": 0.5, "growth": 1, "wins": 1, "win": 1, "settlement": 0.5, "dovish": 1, "cut": 0.5}
NEG = {"crash": 2, "crashes": 2, "plunge": 2, "plunges": 2, "tumble": 2, "tumbles": 2, "slump": 2, "drop": 1, "drops": 1, "fall": 1, "falls": 1,
       "dump": 2, "sell-off": 2, "selloff": 2, "bearish": 2, "hack": 2, "hacked": 2, "exploit": 2, "exploited": 2, "stolen": 2, "theft": 2,
       "ban": 2, "bans": 2, "banned": 2, "lawsuit": 2, "sues": 2, "sued": 2, "fraud": 2, "scam": 2, "rug": 2, "outflow": 1, "outflows": 1,
       "liquidation": 1, "liquidations": 1, "liquidated": 1, "delist": 1, "delists": 1, "delisting": 1, "insolvency": 2, "bankruptcy": 2,
       "collapse": 2, "fear": 1, "panic": 2, "warning": 1, "warns": 1, "risk": 0.5, "probe": 1, "investigation": 1, "fine": 1, "fined": 1,
       "decline": 1, "declines": 1, "loss": 1, "losses": 1, "lose": 1, "weak": 1, "hawkish": 1, "tightening": 1, "default": 2, "downgrade": 1}
NEGATORS = {"not", "no", "never", "without", "fails", "fail", "denies", "denied", "rejects", "rejected", "unlikely"}
ASSET_WORDS = {"BTC": ("bitcoin", "btc"), "ETH": ("ethereum", "ether", "eth"), "SOL": ("solana", "sol"), "XRP": ("xrp", "ripple"),
               "BNB": ("bnb",), "DOGE": ("dogecoin", "doge"), "ADA": ("cardano", "ada"), "LINK": ("chainlink",), "AVAX": ("avalanche", "avax"),
               "SUI": ("sui",), "LTC": ("litecoin", "ltc"), "TRX": ("tron", "trx"), "TON": ("toncoin",), "SHIB": ("shiba",)}


def _weight(tok: str) -> float:
    """Peso de una palabra, probando formas sencillas (plural, -ed, -ing) para no depender de listar todas las conjugaciones."""
    cands = [tok]
    if tok.endswith("s"):
        cands.append(tok[:-1])
    if tok.endswith("ed"):
        cands += [tok[:-2], tok[:-1]]
    if tok.endswith("ing"):
        cands += [tok[:-3], tok[:-3] + "e"]
    for c in cands:
        w = POS.get(c, 0.0) - NEG.get(c, 0.0)
        if w:
            return w
    return 0.0


def score_text(text: str) -> float:
    """Tono en [-1, 1] con el léxico de arriba: suma de pesos (con negación en las 3 palabras previas) / 3, recortado."""
    toks = re.findall(r"[a-z][a-z\-']*", (text or "").lower())
    total = 0.0
    for i, t in enumerate(toks):
        w = _weight(t)
        if w == 0.0:
            continue
        if any(n in NEGATORS for n in toks[max(0, i - 3): i]):
            w = -w
        total += w
    return float(max(-1.0, min(1.0, total / 3.0)))


def detect_assets(text: str) -> list[str]:
    toks = set(re.findall(r"[a-z]+", (text or "").lower()))
    return [a for a, words in ASSET_WORDS.items() if any(w in toks for w in words)]


def _strip(s: Optional[str]) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", s or "")).strip()


def _ts(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    try:
        return int(parsedate_to_datetime(s).timestamp() * 1000)
    except (TypeError, ValueError):
        try:
            return int(pd.Timestamp(s).timestamp() * 1000)
        except (ValueError, TypeError):
            return None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_feed(data: bytes | str, source: str, now_ms: Optional[int] = None) -> list[dict]:
    """RSS 2.0 o Atom → [{id, source, title, url, ts_pub, ts_seen, summary}]. Rechaza XML con entidades (ataques de expansión)."""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    if len(raw) > MAX_XML_BYTES or b"<!ENTITY" in raw:
        raise ValueError("feed demasiado grande o con entidades XML")
    root = ET.fromstring(raw)
    now_ms = now_ms or int(time.time() * 1000)
    out = []
    for node in root.iter():
        if _local(node.tag) not in ("item", "entry"):
            continue
        f = {}
        for ch in node:
            n = _local(ch.tag)
            if n == "title":
                f["title"] = _strip("".join(ch.itertext()))
            elif n == "link":
                f["url"] = (ch.get("href") or (ch.text or "")).strip()
            elif n in ("pubDate", "published", "updated", "date") and "ts" not in f:
                f["ts"] = _ts(ch.text)
            elif n in ("description", "summary", "content") and "summary" not in f:
                f["summary"] = _strip("".join(ch.itertext()))[:200]
        if not f.get("title"):
            continue
        key = f.get("url") or f["title"]
        out.append({"id": hashlib.sha1(f"{source}|{key}".encode()).hexdigest()[:16], "source": source, "title": f["title"][:300],
                    "url": f.get("url", ""), "ts_pub": f.get("ts"), "ts_seen": now_ms, "summary": f.get("summary", "")})
    return out


def parse_stocktwits(payload: dict, asset: str, now_ms: Optional[int] = None) -> list[dict]:
    """Mensajes públicos con la etiqueta de sentimiento que el propio autor puso (Bullish/Bearish) cuando la puso."""
    now_ms = now_ms or int(time.time() * 1000)
    out = []
    for m in payload.get("messages") or []:
        sent = ((m.get("entities") or {}).get("sentiment") or {}).get("basic")
        out.append({"id": f"st:{m.get('id')}", "source": f"stocktwits_{asset}", "title": _strip(m.get("body"))[:200], "url": "",
                    "ts_pub": _ts(m.get("created_at")), "ts_seen": now_ms, "summary": "",
                    "tag": {"Bullish": 1, "Bearish": -1}.get(sent, 0)})
    return out


def add_scores(items: list[dict]) -> list[dict]:
    for it in items:
        it["score"] = score_text(it["title"] + " " + it.get("summary", ""))
        it["lex"] = LEXICON_VERSION
        it["assets"] = detect_assets(it["title"] + " " + it.get("summary", ""))
    return items


def merge_items(store: list[dict], new: list[dict], cap: int = MAX_ITEMS) -> tuple[list[dict], int]:
    have = {x["id"] for x in store}
    add = [x for x in new if x["id"] not in have]
    seen = set()
    add = [x for x in add if not (x["id"] in seen or seen.add(x["id"]))]
    merged = store + add
    merged.sort(key=lambda x: (x.get("ts_seen") or 0, x["id"]))
    return merged[-cap:], len(add)


def daily_tone(items: list[dict]) -> pd.DataFrame:
    """Agrega por día UTC de OBSERVACIÓN (ts_seen): n, tono medio, % positivos/negativos, dispersión, para el mercado y para BTC/ETH.
    Stocktwits (etiquetas de sus autores) se resume aparte: balance = (alcistas − bajistas)/etiquetados."""
    rows = {}
    for it in items:
        d = pd.Timestamp(it["ts_seen"], unit="ms").normalize()
        r = rows.setdefault(d, {"all": [], "BTC": [], "ETH": [], "st_bull": 0, "st_bear": 0, "reddit": 0, "media": 0})
        if it["source"].startswith("stocktwits_"):
            r["st_bull"] += it.get("tag", 0) == 1
            r["st_bear"] += it.get("tag", 0) == -1
            continue
        r["all"].append(it["score"])
        r["reddit" if it["source"].startswith("reddit_") else "media"] += 1
        for a in ("BTC", "ETH"):
            if a in it.get("assets", []):
                r[a].append(it["score"])
    recs = []
    for d, r in sorted(rows.items()):
        a = np.array(r["all"], dtype=float)
        tagged = r["st_bull"] + r["st_bear"]
        recs.append({"date": d, "n": len(a), "n_media": r["media"], "n_reddit": r["reddit"], "tone": float(a.mean()) if len(a) else np.nan,
                     "tone_std": float(a.std()) if len(a) > 1 else np.nan, "pct_pos": float((a > 0).mean()) if len(a) else np.nan,
                     "pct_neg": float((a < 0).mean()) if len(a) else np.nan,
                     "tone_btc": float(np.mean(r["BTC"])) if r["BTC"] else np.nan, "n_btc": len(r["BTC"]),
                     "tone_eth": float(np.mean(r["ETH"])) if r["ETH"] else np.nan, "n_eth": len(r["ETH"]),
                     "st_balance": (r["st_bull"] - r["st_bear"]) / tagged if tagged else np.nan, "st_tagged": tagged})
    return pd.DataFrame(recs).set_index("date") if recs else pd.DataFrame()
