"""Pruebas del observatorio de spreads: cálculo bruto/neto, rutas de control, filtros de calidad de datos,
persistencia, estado acumulado, regla de parámetros fijos y degradación ante fallas de red.
Todo con mercados inventados: no toca la red."""
import json
import math
import os
import tempfile

import observatory_step as step
from sim import observatory as obs

P = dict(obs.DEFAULT_PARAMS)
FEE_BITSO, FEE_OTHER = 0.0036, 0.0010
SLIP2 = 2 * P["slip_bps"] / 1e4


def snap(quotes, gaps=None, ts=1_000):
    return {"ts": ts, "quotes": quotes, "mxn_gap": gaps or {}}


def q(bid, ask, bq=50_000.0, aq=50_000.0):
    return [bid, ask, bq, aq]


class FakeFetchers:
    """Mercado inventado; `fail` = casas que lanzan excepción."""

    def __init__(self, bitso=None, binance=None, kucoin=None, mxn=None, usdt_mxn=None, fail=()):
        self._b, self._bn, self._k = bitso or {}, binance or {}, kucoin or {}
        self._mxn, self._um, self.fail = mxn or {}, usdt_mxn, set(fail)
        self.size_calls = []

    def bitso(self):
        if "bitso" in self.fail:
            raise RuntimeError("bitso caído")
        return self._b, self._mxn, self._um

    def binance(self):
        if "binance" in self.fail:
            raise RuntimeError("binance bloqueado")
        return self._bn

    def kucoin(self):
        if "kucoin" in self.fail:
            raise RuntimeError("kucoin caído")
        return self._k

    def top_size(self, venue, asset):
        self.size_calls.append((venue, asset))
        return 40_000.0, 40_000.0


# ------------------------------------------------------------------------------ cálculo del spread
def test_net_spread_subtracts_both_fees_and_slippage():
    s = snap({"XRP": {"bitso": q(1.3190, 1.3200), "binance": q(1.3400, 1.3401)}})
    rows, susp = obs.evaluate_snapshot(s, P)
    r = {x["route"]: x for x in rows}["bitso>binance"]          # compra en Bitso (ask 1.3200), vende en Binance (bid 1.3400)
    gross = 1.3400 / 1.3200 - 1
    assert math.isclose(r["gross"], gross)
    assert math.isclose(r["net"], gross - FEE_BITSO - FEE_OTHER - SLIP2)
    assert susp == 0 and not r["control"]
    back = {x["route"]: x for x in rows}["binance>bitso"]      # la ruta inversa es claramente negativa
    assert back["net"] < -0.02


def test_every_ordered_pair_is_a_route_and_binance_kucoin_is_control():
    s = snap({"ADA": {"bitso": q(0.40, 0.401), "binance": q(0.4005, 0.4006), "kucoin": q(0.4004, 0.4007)}})
    rows, _ = obs.evaluate_snapshot(s, P)
    assert len(rows) == 6                                        # 3 casas -> 6 rutas ordenadas
    ctrl = {x["route"] for x in rows if x["control"]}
    assert ctrl == {"binance>kucoin", "kucoin>binance"}


def test_depth_is_the_thinner_of_the_two_legs_in_usdt():
    s = snap({"XRP": {"bitso": q(1.30, 1.32, 1e5, 10_000), "binance": q(1.40, 1.41, 20_000, 1e5)}})
    rows, _ = obs.evaluate_snapshot(s, P)
    r = {x["route"]: x for x in rows}["bitso>binance"]
    assert math.isclose(r["depth"], min(10_000 * 1.32, 20_000 * 1.40))


# ------------------------------------------------------------------------------ calidad de datos
def test_suspicious_gross_spread_is_dropped_and_counted():
    s = snap({"FOO": {"bitso": q(1.0, 1.001), "binance": q(1.6, 1.601)}})   # +60 %: casi seguro tickers distintos
    rows, susp = obs.evaluate_snapshot(s, P)
    assert rows == [] and susp == 2                               # las dos direcciones superan el 20 % de bruto


def test_illiquid_books_are_ignored():
    wide = q(1.00, 1.10)                                          # 10 % de spread interno
    s = snap({"BAR": {"bitso": wide, "binance": q(1.5, 1.501)}})
    rows, susp = obs.evaluate_snapshot(s, P)
    assert rows == [] and susp == 0


def test_parsers_drop_crossed_zero_and_non_usdt_books():
    bitso = {"payload": [
        {"book": "xrp_usdt", "bid": "1.30", "ask": "1.31"},
        {"book": "btc_usdt", "bid": "70000", "ask": "69000"},       # cruzado
        {"book": "eth_usdt", "bid": "0", "ask": "0"},               # detenido
        {"book": "xrp_mxn", "bid": "26.0", "ask": "26.2"},
        {"book": "usdt_mxn", "bid": "19.9", "ask": "20.1"},
        {"book": "btc_usd", "bid": "70000", "ask": "70010"}]}       # otra cotización: se ignora
    usdt, mxn_mid, um = obs.parse_bitso_tickers(bitso)
    assert set(usdt) == {"XRP"} and math.isclose(mxn_mid["XRP"], 26.1) and math.isclose(um, 20.0)
    bn = obs.parse_binance_book_tickers([
        {"symbol": "XRPUSDT", "bidPrice": "1.30", "askPrice": "1.31", "bidQty": "5", "askQty": "6"},
        {"symbol": "XRPBTC", "bidPrice": "0.00002", "askPrice": "0.00003", "bidQty": "1", "askQty": "1"},
        {"symbol": "DEADUSDT", "bidPrice": "0.00", "askPrice": "0.00", "bidQty": "0", "askQty": "0"}])
    assert set(bn) == {"XRP"} and bn["XRP"][2] == 5.0
    kc = obs.parse_kucoin_all_tickers({"data": {"ticker": [
        {"symbol": "XRP-USDT", "buy": "1.30", "sell": "1.31"}, {"symbol": "XRP-BTC", "buy": "1", "sell": "2"},
        {"symbol": "NOPE-USDT", "buy": None, "sell": None}]}})
    assert set(kc) == {"XRP"} and math.isnan(kc["XRP"][2])


def test_snapshot_only_covers_bitso_assets_and_needs_two_venues():
    f = FakeFetchers(bitso={"XRP": q(1.30, 1.31)}, binance={"XRP": q(1.30, 1.31), "SOL": q(150, 150.1)},
                     kucoin={"XRP": q(1.30, 1.31)})
    s = obs.take_snapshot(f, 5)
    assert set(s["quotes"]) == {"XRP"} and set(s["quotes"]["XRP"]) == {"bitso", "binance", "kucoin"}
    assert obs.take_snapshot(FakeFetchers(bitso={"XRP": q(1.3, 1.31)}), 5) is None     # nadie más con quien comparar
    assert obs.take_snapshot(FakeFetchers(binance={"XRP": q(1.3, 1.31)}, fail=("bitso",)), 5) is None


def test_snapshot_survives_one_venue_failing():
    f = FakeFetchers(bitso={"XRP": q(1.30, 1.31)}, binance={"XRP": q(1.31, 1.32)}, fail=("kucoin",))
    s = obs.take_snapshot(f, 5)
    assert set(s["quotes"]["XRP"]) == {"bitso", "binance"}


def test_mxn_gap_is_implied_usdt_price_vs_reference():
    f = FakeFetchers(bitso={"XRP": q(1.30, 1.31)}, binance={"XRP": q(1.30, 1.31)}, mxn={"XRP": 26.55}, usdt_mxn=20.0)
    s = obs.take_snapshot(f, 5)
    assert math.isclose(s["mxn_gap"]["XRP"], (26.55 / 20.0) / 1.305 - 1)


# ------------------------------------------------------------------------------ estado acumulado
def test_stats_count_threshold_and_events_and_persistence():
    st = obs.new_state(P, now_ms=0)
    opp = snap({"XRP": {"bitso": q(1.3190, 1.3200), "binance": q(1.3400, 1.3401)}}, ts=1_000)
    flat = snap({"XRP": {"bitso": q(1.3290, 1.3300), "binance": q(1.3295, 1.3296)}}, ts=21_000)
    rows, susp = obs.evaluate_snapshot(opp, P)
    prev = obs.update_stats(st, opp, rows, susp, set())
    assert prev == {"XRP|bitso>binance"}
    rows, susp = obs.evaluate_snapshot(opp, P)                    # sigue ahí en la foto siguiente -> persistió
    prev = obs.update_stats(st, opp, rows, susp, prev)
    rows, susp = obs.evaluate_snapshot(flat, P)
    obs.update_stats(st, flat, rows, susp, prev)                  # ya no hay oportunidad
    s = st["routes"]["XRP|bitso>binance"]
    assert s["n"] == 3 and s["n_thr"] == 2 and s["n_pos"] == 2
    assert s["persist_n"] == 2 and s["persist_hit"] == 1          # de dos veces "vistas", una sobrevivió
    assert len(st["events"]) == 2 and st["snapshots"] == 3
    # cota superior: tamaño = min(profundidad, tope) × neto, solo cuando la profundidad es conocida
    gross = 1.3400 / 1.3200 - 1
    net = gross - FEE_BITSO - FEE_OTHER - SLIP2
    depth = min(50_000 * 1.32, 50_000 * 1.34)
    assert math.isclose(s["pnl_ub"], 2 * min(depth, P["cap_usdt"]) * net)


def test_unknown_depth_does_not_inflate_the_upper_bound():
    st = obs.new_state(P, now_ms=0)
    nan = float("nan")
    sn = snap({"XRP": {"bitso": q(1.3190, 1.3200, nan, nan), "binance": q(1.3400, 1.3401, nan, nan)}})
    rows, susp = obs.evaluate_snapshot(sn, P)
    obs.update_stats(st, sn, rows, susp, set())
    s = st["routes"]["XRP|bitso>binance"]
    assert s["n_thr"] == 1 and s["pnl_ub"] == 0.0 and s["thr_depth_known"] == 0


def test_top_size_is_requested_only_for_positive_net_routes_with_missing_depth():
    nan = float("nan")
    f = FakeFetchers()
    sn = snap({"XRP": {"bitso": q(1.3190, 1.3200, nan, nan), "binance": q(1.3400, 1.3401, 9_000.0, 9_000.0)},
               "ADA": {"bitso": q(0.40, 0.401, nan, nan), "binance": q(0.4005, 0.4006, 9_000.0, 9_000.0)}})
    rows, _ = obs.evaluate_snapshot(sn, P, f.top_size)
    assert ("bitso", "XRP") in f.size_calls and all(a == "XRP" for _, a in f.size_calls)   # ADA no tiene neto > 0
    r = {(x["asset"], x["route"]): x for x in rows}[("XRP", "bitso>binance")]
    assert r["depth"] == min(40_000 * 1.32, 9_000 * 1.34)


def test_state_size_is_bounded_and_event_log_rolls():
    p = dict(P, event_log=5)
    st = obs.new_state(p, now_ms=0)
    for i in range(50):
        sn = snap({"XRP": {"bitso": q(1.3190, 1.3200), "binance": q(1.3400, 1.3401)}}, ts=1_000 * (i + 1))
        rows, susp = obs.evaluate_snapshot(sn, p)
        obs.update_stats(st, sn, rows, susp, set())
    assert len(st["events"]) == 5 and st["events"][-1]["ts"] == 50_000
    assert len(st["routes"]) == 2 and st["routes"]["XRP|bitso>binance"]["n"] == 50


def test_histogram_buckets_cover_the_tails():
    assert obs.hist_index(-0.5) == 0 and obs.hist_index(0.5) == obs.HIST_BINS - 1
    assert obs.hist_index(-0.001) == 7 and obs.hist_index(0.001) == 8      # sin tocar los bordes (evita ruido de coma flotante)
    assert obs.hist_index(obs.DEFAULT_PARAMS["threshold"]) > obs.hist_index(0.001)
    assert len(obs.hist_labels()) == obs.HIST_BINS


# ------------------------------------------------------------------------------ resumen y veredicto
def test_summary_has_no_verdict_before_30_days_and_compares_bitso_vs_control():
    st = obs.new_state(P, now_ms=0)
    sn = snap({"XRP": {"bitso": q(1.3190, 1.3200), "binance": q(1.3400, 1.3401), "kucoin": q(1.3399, 1.3402)}},
              gaps={"XRP": 0.007}, ts=2 * 86_400_000)
    rows, susp = obs.evaluate_snapshot(sn, P)
    obs.update_stats(st, sn, rows, susp, set())
    sm = obs.summarize(st)
    assert sm["days"] == 2.0 and sm["verdict"].startswith("Sin veredicto")
    assert sm["bitso"]["pct_thr"] > 0 and sm["control"]["pct_thr"] == 0       # el spread vive en las rutas con Bitso
    top = sm["routes"][0]
    assert top["asset"] == "XRP" and not top["control"] and top["pnl_ub_per_day"] > 0
    assert sm["mxn_gaps"][0]["asset"] == "XRP" and sm["mxn_gaps"][0]["pct_flag"] == 1.0
    md = obs.render_markdown(sm)
    assert "Sin veredicto" in md and "XRP" in md and "Medición, no garantía" in md


def test_summary_gives_a_verdict_after_enough_days():
    st = obs.new_state(P, now_ms=0)
    sn = snap({"XRP": {"bitso": q(1.30, 1.31), "binance": q(1.30, 1.31)}}, ts=31 * 86_400_000)
    rows, susp = obs.evaluate_snapshot(sn, P)
    obs.update_stats(st, sn, rows, susp, set())
    assert not obs.summarize(st)["verdict"].startswith("Sin veredicto")


# ------------------------------------------------------------------------------ corrida completa
def _market():
    return FakeFetchers(bitso={"XRP": q(1.3190, 1.3200)}, binance={"XRP": q(1.3400, 1.3401)},
                        kucoin={"XRP": q(1.3395, 1.3402)}, mxn={"XRP": 26.4}, usdt_mxn=20.0)


def test_run_writes_outputs_and_accumulates_across_runs():
    with tempfile.TemporaryDirectory() as d:
        out1, out2 = os.path.join(d, "o1"), os.path.join(d, "o2")
        code, _ = step.run(None, out1, 3, 0, fetchers=_market(), sleep=lambda s: None)
        assert code == 0
        stats = os.path.join(out1, "stats.json")
        assert all(os.path.exists(os.path.join(out1, n)) for n in ("stats.json", "summary.json", "summary.md", "status.json"))
        json.load(open(os.path.join(out1, "summary.json"), encoding="utf-8"))   # JSON estricto, sin NaN
        code, _ = step.run(stats, out2, 3, 0, fetchers=_market(), sleep=lambda s: None)
        assert code == 0
        st = json.load(open(os.path.join(out2, "stats.json"), encoding="utf-8"))
        assert st["runs"] == 2 and st["snapshots"] == 6 and st["routes"]["XRP|bitso>binance"]["n"] == 6


def test_run_refuses_changed_parameters_midway():
    with tempfile.TemporaryDirectory() as d:
        out1, out2 = os.path.join(d, "o1"), os.path.join(d, "o2")
        step.run(None, out1, 1, 0, fetchers=_market(), sleep=lambda s: None)
        code, status = step.run(os.path.join(out1, "stats.json"), out2, 1, 0, fetchers=_market(), sleep=lambda s: None,
                                params=dict(P, threshold=0.001))
        assert code == 1 and "parámetros" in status["message"] and not os.path.exists(os.path.join(out2, "stats.json"))


def test_run_fresh_keeps_previous_state():
    with tempfile.TemporaryDirectory() as d:
        out1, out2 = os.path.join(d, "o1"), os.path.join(d, "o2")
        step.run(None, out1, 1, 0, fetchers=_market(), sleep=lambda s: None)
        state_copy = os.path.join(d, "stats.json")
        os.replace(os.path.join(out1, "stats.json"), state_copy)
        code, _ = step.run(state_copy, out2, 1, 0, fresh=True, fetchers=_market(), sleep=lambda s: None)
        assert code == 0 and os.path.exists(os.path.join(d, "stats.prev.json"))
        assert json.load(open(os.path.join(out2, "stats.json"), encoding="utf-8"))["runs"] == 1


def test_run_without_data_returns_2_and_writes_no_state():
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "o")
        code, status = step.run(None, out, 2, 0, fetchers=FakeFetchers(fail=("bitso",)), sleep=lambda s: None)
        assert code == 2 and "Sin datos" in status["message"]
        assert not os.path.exists(os.path.join(out, "stats.json")) and os.path.exists(os.path.join(out, "status.json"))


def test_partial_failures_still_count_the_good_snapshots():
    class Flaky(FakeFetchers):
        calls = 0

        def bitso(self):
            Flaky.calls += 1
            if Flaky.calls % 2 == 0:
                raise RuntimeError("timeout")
            return super().bitso()

    st = obs.new_state(P, now_ms=0)
    good = obs.observe(st, Flaky(bitso={"XRP": q(1.31, 1.32)}, binance={"XRP": q(1.31, 1.32)}), snapshots=4, interval_s=0,
                       sleep=lambda s: None)
    assert good == 2 and st["failed_snapshots"] == 2 and st["snapshots"] == 2
