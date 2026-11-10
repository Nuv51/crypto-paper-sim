#!/usr/bin/env python
"""Observatorio de mercado — una corrida horaria (solo mide y registra; no opera, no envía órdenes, no toca los simuladores).

  python mercado_step.py --store store/mercado                       # fuentes públicas reales
Estado en  <store>/state/ : closes.csv · flows.json · events.json · items.json · predictions.json · event_study.json
Salida en  <store>/data/  : mercado.json (todo lo que muestra la página) · status.json
Cada fuente falla por separado (queda registrada en status.fuentes y esa serie queda con hueco ese día). Código 0 si escribió salida, 1 si
hubo un error inesperado, 2 si no hubo NINGUNA fuente.
Fases (ver OBSERVATORIO_MERCADO.md): 0 rangos de 12 m (resultados fijos de la corrida en frío + estado de hoy) · 1 flujos y derivados ·
2 anuncios y calendario · 3 noticias y redes · predicciones registradas con fecha.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from typing import Callable, Optional

import numpy as np
import pandas as pd

import config_index
from mercado_fase0_run import _clean
from sim import market_eval as ev
from sim import market_events as me
from sim import market_feeds as mf
from sim import market_pred as mp
from sim import market_ranges as mr
from sim import market_text as mt
from sim.data import INTERVAL_MS, _http_json

DAY = 86_400_000
START_MS = int(pd.Timestamp("2017-07-01", tz="UTC").timestamp() * 1000)
FLOWS_CAP = 24 * 400
HERE = os.path.dirname(os.path.abspath(__file__))
FASE0_RESULTS = os.path.join(HERE, "mercado_fase0_results.json")


class Net:
    """Acceso a la red (inyectable en pruebas)."""

    def __init__(self, session=None):
        self.s = session or mf.make_session()

    def json(self, url, params=None):
        return _http_json(self.s, url, params, retries=2, timeout=20)

    def fng(self):
        return mf.fetch_fear_greed(self.s)

    def bytes(self, url, params=None):
        r = self.s.get(url, params=params, timeout=25)
        r.raise_for_status()
        return r.content


# ----------------------------------------------------------------------------- estado
def _load(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(_clean(obj), fh, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    os.replace(tmp, path)


def _save_lines(path, obj):
    """Igual que _save pero con UN registro por línea: git guarda solo las líneas nuevas en cada commit (el historial no crece con el archivo entero)."""
    obj = _clean(obj)
    tmp = path + ".tmp"
    dump = lambda x: json.dumps(x, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    with open(tmp, "w", encoding="utf-8") as fh:
        if isinstance(obj, dict) and "rows" in obj:
            head = {k: v for k, v in obj.items() if k != "rows"}
            fh.write(dump(head)[:-1] + ',"rows":[\n' + ",\n".join(dump(r) for r in obj["rows"]) + "\n]}\n")
        else:
            fh.write("[\n" + ",\n".join(dump(r) for r in obj) + "\n]\n")
    os.replace(tmp, path)


def load_closes(path) -> dict[str, pd.Series]:
    if not os.path.exists(path):
        return {}
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    return {c: df[c].dropna() for c in df.columns}


def save_closes(path, closes):
    tmp = path + ".tmp"
    pd.DataFrame(closes).sort_index().to_csv(tmp, index_label="fecha", float_format="%.10g")
    os.replace(tmp, path)


def fetch_daily(net: Net, symbol: str, start_ms: int, now_ms: int, pause: float = 0.15) -> pd.Series:
    """Cierres diarios CERRADOS (la vela de hoy aún no cuenta) desde start_ms, paginando de 1000 en 1000."""
    out, cursor = [], start_ms
    while True:
        rows = net.json(f"{mf.BINANCE}/api/v3/klines", {"symbol": symbol, "interval": "1d", "limit": 1000, "startTime": int(cursor)})
        if not rows:
            break
        out += [(int(r[0]), float(r[4])) for r in rows if int(r[6]) < now_ms]
        if len(rows) < 1000:
            break
        cursor = int(rows[-1][0]) + INTERVAL_MS["1d"]
        time.sleep(pause)
    if not out:
        return pd.Series(dtype=float)
    ser = pd.Series([c for _, c in out], index=pd.to_datetime([t for t, _ in out], unit="ms").normalize())
    return ser[~ser.index.duplicated(keep="last")]


def update_closes(net: Net, closes: dict, now_ms: int, symbols, status: dict) -> bool:
    """Una vez al día (cuando falta el cierre de ayer) baja lo nuevo de cada moneda. Devuelve True si cambió algo."""
    yesterday = pd.Timestamp(now_ms, unit="ms").normalize() - pd.Timedelta(days=1)
    changed = False
    for sym in symbols:
        have = closes.get(sym)
        if have is not None and len(have) and have.index[-1] >= yesterday:
            continue
        start = START_MS if have is None or not len(have) else int((have.index[-1] - pd.Timedelta(days=10)).timestamp() * 1000)
        try:
            new = fetch_daily(net, sym, start, now_ms)
        except Exception as e:
            status[f"closes_{sym}"] = f"{type(e).__name__}: {e}"[:120]
            continue
        if len(new):
            closes[sym] = new if have is None else pd.concat([have[~have.index.isin(new.index)], new]).sort_index()
            changed = True
    return changed


# ----------------------------------------------------------------------------- fase 2 y 3: fuentes
def collect_events(net: Net, status: dict, fomc_html: Optional[str]) -> list[dict]:
    new: list[dict] = []

    def go(name, fn):
        try:
            new.extend(fn())
            status[name] = "ok"
        except Exception as e:
            status[name] = f"{type(e).__name__}: {e}"[:160]

    for kind, cat in me.BINANCE_CATALOGS.items():
        go(f"anuncios_binance_{kind}", lambda kind=kind, cat=cat: me.parse_binance_cms(
            net.json(me.BINANCE_CMS, {"type": 1, "catalogId": cat, "pageNo": 1, "pageSize": 5}), kind))
    for kind, t in (("listing", "announcements-new-listings"), ("delisting", "announcements-delistings")):
        go(f"anuncios_okx_{kind}", lambda kind=kind, t=t: me.parse_okx_announcements(net.json(me.OKX_ANN, {"annType": t}), kind))
    for kind, t in (("listing", "new-listings"), ("delisting", "delistings")):
        go(f"anuncios_kucoin_{kind}", lambda kind=kind, t=t: me.parse_kucoin_announcements(
            net.json(me.KUCOIN_ANN, {"annType": t, "lang": "en_US", "pageSize": 30}), kind))
    new.extend(me.fomc_events(fomc_html))
    return new


def collect_news(net: Net, now_ms: int, status: dict, sleep: Callable = time.sleep) -> list[dict]:
    items: list[dict] = []
    for src, url in mt.FEEDS.items():
        try:
            items += mt.parse_feed(net.bytes(url), src, now_ms)
            status[f"feed_{src}"] = "ok"
        except Exception as e:
            status[f"feed_{src}"] = f"{type(e).__name__}: {e}"[:160]
        if src.startswith("reddit_"):
            sleep(8.0)                                   # Reddit limita peticiones sin sesión (429): espacio generoso; si aun así falla, queda registrado
    for a, url in mt.STOCKTWITS.items():
        try:
            items += mt.parse_stocktwits(net.json(url), a, now_ms)
            status[f"stocktwits_{a}"] = "ok"
        except Exception as e:
            status[f"stocktwits_{a}"] = f"{type(e).__name__}: {e}"[:160]
    return mt.add_scores(items)


# ----------------------------------------------------------------------------- fase 0 (estado de hoy con resultados fijos)
def phase0_today(closes: dict[str, pd.Series]) -> Optional[dict]:
    res = _load(FASE0_RESULTS, None)
    if not res or not closes:
        return None
    results = {lab: {int(h): v for h, v in d.items()} for lab, d in res["results"].items()}
    recent = {k: s.iloc[-1300:] for k, s in closes.items() if len(s) > 400}
    if not recent:
        return None
    hoy = mr.today_state(mr.Panel(recent), results)
    return {"hoy": hoy, "resumen": [{"label": lab, "texto": mr.LABEL_TEXT[lab], "h": h, "veredicto": res["results"][lab][str(h)]["veredicto"],
                                      "motivo": res["results"][lab][str(h)]["motivo"],
                                      "ep_desc": res["results"][lab][str(h)]["descubrimiento"]["n_episodios_mercado"],
                                      "ep_conf": res["results"][lab][str(h)]["confirmacion"]["n_episodios_mercado"],
                                      "exceso_desc": res["results"][lab][str(h)]["descubrimiento"]["exceso"],
                                      "exceso_conf": res["results"][lab][str(h)]["confirmacion"]["exceso"],
                                      "p_desc": res["results"][lab][str(h)]["descubrimiento"]["p"],
                                      "mediana": res["results"][lab][str(h)]["todo"]["mediana"],
                                      "pct_positivo": res["results"][lab][str(h)]["todo"]["pct_positivo"]}
                                     for lab in mr.ALL_LABELS for h in mr.HORIZONS],
            "params": res["params"]}


# ----------------------------------------------------------------------------- una corrida
def run(store: str, net: Optional[Net] = None, now_ms: Optional[int] = None, symbols=None, sleep: Callable = time.sleep) -> tuple[int, dict]:
    net = net or Net()
    now_ms = now_ms or int(time.time() * 1000)
    symbols = list(symbols or config_index.TOP25)
    st_dir, out_dir = os.path.join(store, "state"), os.path.join(store, "data")
    os.makedirs(st_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)
    status: dict = {}
    today = pd.Timestamp(now_ms, unit="ms").normalize()
    try:
        # --- precios diarios
        closes = load_closes(os.path.join(st_dir, "closes.csv"))
        if update_closes(net, closes, now_ms, symbols, status):
            save_closes(os.path.join(st_dir, "closes.csv"), closes)
        # --- fase 1: foto de flujos y derivados
        flows = _load(os.path.join(st_dir, "flows.json"), {"cols": mf.FLOW_COLUMNS, "rows": []})
        row, fstat, kc = mf.collect_flows(net.s, now_ms, get=net.json, fng_fn=net.fng)
        status.update(fstat)
        rows = [r for r in flows["rows"] if r[0] != row["ts"]] + [[row[c] for c in flows["cols"]]]
        flows["rows"] = rows[-FLOWS_CAP:]
        _save_lines(os.path.join(st_dir, "flows.json"), flows)
        # --- fase 2: anuncios y calendario
        fomc_html = None
        try:
            fomc_html = net.bytes(me.FED_FOMC).decode("utf-8", "replace")
            status["fed_calendario"] = "ok"
        except Exception as e:
            status["fed_calendario"] = f"{type(e).__name__}: {e}"[:160]
        new_events = collect_events(net, status, fomc_html)
        allowed_fomc = {e["id"] for e in new_events if e["kind"] == "fomc"}
        stored = [e for e in _load(os.path.join(st_dir, "events.json"), []) if e["kind"] != "fomc" or e["id"] in allowed_fomc]   # limpia fechas que ya no se consideran reuniones
        events, n_new_ev = me.merge_events(stored, new_events)
        _save_lines(os.path.join(st_dir, "events.json"), events)
        # --- fase 3: noticias y redes
        items, n_new_it = mt.merge_items(_load(os.path.join(st_dir, "items.json"), []), collect_news(net, now_ms, status, sleep))
        _save_lines(os.path.join(st_dir, "items.json"), items)
        # --- predicciones registradas
        preds = _load(os.path.join(st_dir, "predictions.json"), [])
        asof = today - pd.Timedelta(days=1)
        new_preds = []
        for a in mf.ASSETS:
            cs = closes.get(a + "USDT")
            if cs is not None and asof in cs.index:
                p = mp.make_prediction(a, cs.loc[:asof], str(asof.date()), row.get(f"{a.lower()}_dvol"))
                if p:
                    new_preds.append(p)
        preds = mp.merge_predictions(preds, new_preds)
        n_res = mp.resolve(preds, closes)
        _save_lines(os.path.join(st_dir, "predictions.json"), preds)
        # --- evaluaciones (se recalculan de los datos acumulados; "sin veredicto" hasta tener suficientes días)
        daily = ev.flow_daily(flows["rows"], flows["cols"])
        fl_eval = ev.evaluate_flows(daily, closes)
        tone = mt.daily_tone(items)
        fng = daily["fng"] if len(daily) and "fng" in daily else None
        se_eval = ev.evaluate_sentiment(tone, closes, fng)
        es = _load(os.path.join(st_dir, "event_study.json"), {})
        if es.get("date") != str(today.date()):
            es = {"date": str(today.date()), "tipos": event_studies(net, events, closes, status)}
            _save(os.path.join(st_dir, "event_study.json"), es)
        # --- fase 0 hoy
        p0 = phase0_today(closes)
        data = build_output(now_ms, row, flows, daily, kc, events, items, tone, preds, n_res, fl_eval, se_eval, es, p0, status, n_new_ev, n_new_it)
        _save(os.path.join(out_dir, "mercado.json"), data)
        n_ok = sum(1 for v in status.values() if v == "ok")
        _save(os.path.join(out_dir, "status.json"), {"ts": now_ms, "fuentes": status, "ok": n_ok, "total": len(status)})
        if n_ok == 0:
            return 2, {"message": "ninguna fuente respondió"}
        return 0, {"ok": n_ok, "total": len(status), "eventos_nuevos": n_new_ev, "titulares_nuevos": n_new_it, "predicciones": len(preds)}
    except Exception:
        err = traceback.format_exc()
        _save(os.path.join(out_dir, "status.json"), {"ts": now_ms, "error": err[-800:], "fuentes": status})
        print(err, file=sys.stderr)
        return 1, {"message": err[-300:]}


def event_studies(net: Net, events: list[dict], closes: dict, status: dict, max_symbols: int = 60) -> dict:
    """Estudio de eventos por tipo (una vez al día). Para listados/retiros baja precios diarios de cada moneda anunciada (si existe en Binance)."""
    out = {}
    for kind in ("fomc", "listing", "delisting"):
        evs = [e for e in events if e["kind"] == kind and e.get("symbols")]
        if kind != "fomc" and len(evs) < me.MIN_EVENTS_STUDY:
            out[kind] = {"n_eventos": len(evs), "veredicto": "sin veredicto", "motivo": f"muestra pequeña ({len(evs)} anuncios; mínimo {me.MIN_EVENTS_STUDY})", "ventanas": {}}
            continue
        px = dict(closes)
        if kind != "fomc":
            need = []
            for e in sorted(evs, key=lambda e: -e["ts_pub"]):
                for s in e["symbols"]:
                    if s + "USDT" not in px and s + "USDT" not in need:
                        need.append(s + "USDT")
            for sym in need[:max_symbols]:
                try:
                    ser = fetch_daily(net, sym, START_MS, int(time.time() * 1000))
                    if len(ser):
                        px[sym] = ser
                except Exception:
                    pass
        res = me.event_study(evs, px, n_perm=1000)
        best = res["ventanas"].get("-1_+1", {})
        v, why = me.study_verdict(best) if best else ("sin veredicto", "sin ventana")
        out[kind] = {**res, "veredicto": v, "motivo": why}
    return out


def build_output(now_ms, row, flows, daily, kc, events, items, tone, preds, n_res, fl_eval, se_eval, es, p0, status, n_new_ev, n_new_it) -> dict:
    cols = flows["cols"]
    last_days = daily.tail(30)
    series = {c: [None if pd.isna(v) else float(v) for v in last_days[c]] for c in cols if c != "ts" and c in last_days}
    t30 = tone.tail(30) if len(tone) else tone
    kc_top = sorted(((k, v) for k, v in kc.items() if v.get("oi_usd")), key=lambda kv: -kv[1]["oi_usd"])[:15]
    news = sorted(items, key=lambda x: -(x.get("ts_seen") or 0))[:60]
    news = [{k: x.get(k) for k in ("source", "title", "url", "ts_pub", "score", "assets")} for x in news if not x["source"].startswith("stocktwits")][:40]
    return {
        "generado_ms": now_ms,
        "aviso": "Contexto estadístico medido, no señales de compra o venta ni garantías. Nada aquí opera dinero.",
        "estado_fuentes": status,
        "fase0": p0,
        "fase1": {"ultima": row, "dias_con_datos": int(len(daily)), "serie_diaria": {"fechas": [str(d.date()) for d in last_days.index], **series},
                  "kucoin_top_oi": [{"base": k, **v} for k, v in kc_top], "evaluacion": fl_eval, "minimo_dias": ev.MIN_N},
        "fase2": {"eventos_recientes": events[-40:][::-1], "proximos_fomc": [e for e in events if e["kind"] == "fomc" and e["ts_pub"] >= now_ms][:3],
                  "n_eventos": len(events), "nuevos_en_esta_corrida": n_new_ev, "estudio": es.get("tipos", {}), "estudio_fecha": es.get("date")},
        "fase3": {"titulares": news, "n_items": len(items), "nuevos_en_esta_corrida": n_new_it, "version_lexico": mt.LEXICON_VERSION,
                  "tono_diario": [{"fecha": str(d.date()), **{k: (None if pd.isna(v) else float(v)) for k, v in r.items()}} for d, r in t30.iterrows()] if len(t30) else [],
                  "dias_con_datos": int(len(tone)), "evaluacion": se_eval, "minimo_dias": ev.MIN_N},
        "predicciones": {"recientes": preds[-16:][::-1], "resueltas_ahora": n_res, "marcador": mp.score(preds)},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True, help="carpeta mercado/ de la rama sim-data")
    a = ap.parse_args(argv)
    code, info = run(a.store)
    print(json.dumps(info, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
