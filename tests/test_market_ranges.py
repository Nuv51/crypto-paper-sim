"""Observatorio de mercado, fase 0: etiquetas de rango de 12 meses, episodios, prueba de permutación y veredictos."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sim import market_ranges as mr

DATES = pd.date_range("2017-01-01", "2026-10-31", freq="D")


def _walk(seed, n=None, vol=0.03):
    n = n or len(DATES)
    r = np.random.default_rng(seed)
    return pd.Series(100 * np.exp(np.cumsum(r.normal(0, vol, n))), index=DATES[:n])


def _closes(k=8, seed0=1):
    names = ["BTCUSDT", "ETHUSDT"] + [f"C{i}USDT" for i in range(k - 2)]
    return {n: _walk(seed0 + i) for i, n in enumerate(names)}


def test_min12m_needs_full_window_and_uses_364_prior_closes():
    idx = pd.date_range("2020-01-01", periods=500, freq="D")
    c = pd.Series(100.0 + np.arange(500) * 0.0, index=idx)
    c.iloc[:] = 100 + np.sin(np.arange(500) / 20.0) * 5
    c.iloc[420] = 50.0                                     # mínimo claro del año
    f = mr.coin_features(c)
    assert not f["ready_min12m"].iloc[:364].any()          # sin 364 cierres previos no se evalúa
    assert f["ready_min12m"].iloc[364]
    assert bool(f["min12m"].iloc[420]) and not bool(f["max12m"].iloc[420])
    assert not f["min12m"].iloc[:364].any()
    # el día siguiente no es mínimo (rebota por encima de 50)
    assert not bool(f["min12m"].iloc[421])
    # empate con el mínimo previo cuenta (<=)
    c2 = c.copy(); c2.iloc[430] = 50.0
    assert bool(mr.coin_features(c2)["min12m"].iloc[430])


def test_peor_y_mejor_semana():
    idx = pd.date_range("2020-01-01", periods=600, freq="D")
    c = pd.Series(100 + np.sin(np.arange(600) / 15.0) * 2, index=idx)
    c.iloc[500:] *= 0.5                                    # caída brusca el día 500
    f = mr.coin_features(c)
    assert bool(f["peor_semana"].iloc[500]) and not bool(f["mejor_semana"].iloc[500])
    c2 = c.copy(); c2.iloc[500:] = c.iloc[500:] * 4
    assert bool(mr.coin_features(c2)["mejor_semana"].iloc[500])


def test_vol_percentiles():
    r = np.random.default_rng(3)
    n = 900
    rets = r.normal(0, 0.02, n)
    rets[600:640] = r.normal(0, 0.12, 40)                  # estallido de volatilidad
    rets[760:800] = r.normal(0, 0.0005, 40)                # calma extrema
    c = pd.Series(100 * np.exp(np.cumsum(rets)), index=pd.date_range("2020-01-01", periods=n, freq="D"))
    f = mr.coin_features(c)
    assert f["vol_alta"].iloc[630:660].any() and not f["vol_baja"].iloc[630:660].any()
    assert f["vol_baja"].iloc[790:830].any()
    assert not f["ready_vol_alta"].iloc[:380].any()        # 30 de retornos + 365 de ventana


def test_episode_starts_and_market_episodes():
    F = np.zeros((2, 200), dtype=bool)
    F[0, [5, 6, 7, 20, 60]] = True                         # 20 está a 13 días de 7 → mismo episodio; 60 a 40 → nuevo
    F[1, [62, 150]] = True
    st = mr.episode_starts(F)
    assert list(np.flatnonzero(st[0])) == [5, 60] and list(np.flatnonzero(st[1])) == [62, 150]
    assert mr.count_market_episodes(st) == 3               # {5}, {60, 62}, {150}
    assert mr.count_market_episodes(np.zeros((2, 10), dtype=bool)) == 0


def test_breadth_label_needs_many_coins():
    closes = {f"C{i}": _walk(100 + i, 1200) for i in range(10)}
    # todas se desploman juntas el día 1000 (capitulación amplia)
    for s in closes.values():
        s.iloc[1000:] = s.iloc[1000:] * (s.iloc[:1000].min() / s.iloc[1000]) * 0.5
    p = mr.Panel(closes)
    assert p.flags["capitulacion_amplia"][:, 1000:1008].any()
    assert not p.flags["capitulacion_amplia"][:, :900].any()
    # con menos de 8 monedas con ventana, la etiqueta de amplitud no se activa aunque todas caigan
    p2 = mr.Panel({k: closes[k] for k in list(closes)[:5]})
    assert not p2.flags["capitulacion_amplia"].any()


def _plant(panel, label, dates_idx, jump):
    """Fuerza episodios de `label` en las fechas dadas (todas las monedas) y un retorno posterior conocido."""
    F = np.zeros_like(panel.flags[label])
    for t in dates_idx:
        F[:, t] = True
        panel.close[:, t + 1:] = panel.close[:, t + 1:] * np.exp(jump)
    panel.flags[label] = F & panel.ready[label]


def test_planted_signal_is_detected_with_evidence_and_null_is_not():
    p = mr.Panel(_closes(6, 11))
    t0 = int(np.flatnonzero(p.dates >= pd.Timestamp("2019-06-01"))[0])
    rg = np.random.default_rng(99)
    ev, t = [], t0
    while t < len(p.dates) - 120:                          # espaciado irregular (60-160 d): sin periodicidad que alinee el desplazamiento
        ev.append(t)
        t += int(rg.integers(60, 160))
    _plant(p, "min12m", ev, 0.20)
    r = mr.run_label(p, "min12m", 7, n_perm=1000)
    assert r["descubrimiento"]["exceso"] > 0.15 and r["confirmacion"]["exceso"] > 0.15
    assert r["descubrimiento"]["n_episodios_mercado"] >= 10 and r["confirmacion"]["n_episodios_mercado"] >= 4
    assert r["descubrimiento"]["p"] < mr.ALPHA_DISC
    assert r["veredicto"] == "con evidencia", r["motivo"]
    # el mismo plan con eventos en fechas al azar y SIN salto posterior no debe dar evidencia
    q = mr.Panel(_closes(6, 11))
    rng = np.random.default_rng(5)
    F = np.zeros_like(q.flags["max12m"])
    F[:, rng.choice(np.arange(400, len(q.dates) - 120), 40, replace=False)] = True
    q.flags["max12m"] = F & q.ready["max12m"]
    rq = mr.run_label(q, "max12m", 30, n_perm=300)
    assert rq["veredicto"] != "con evidencia"


def test_small_sample_gives_no_verdict():
    p = mr.Panel(_closes(6, 21))
    t0 = int(np.flatnonzero(p.dates >= pd.Timestamp("2019-06-01"))[0])
    t1 = int(np.flatnonzero(p.dates >= pd.Timestamp("2024-06-01"))[0])
    _plant(p, "min12m", [t0, t0 + 300, t0 + 600, t1, t1 + 200], 0.3)   # 3 episodios de mercado en descubrimiento, 2 en confirmación
    r = mr.run_label(p, "min12m", 7, n_perm=50)
    assert r["veredicto"] == "sin veredicto" and "muestra pequeña" in r["motivo"], r


def test_verdict_rules():
    ok = {"n_episodios_mercado": 12, "p": 0.001, "exceso": 0.05}
    cf = {"n_episodios_mercado": 5, "p": 0.03, "exceso": 0.04}
    assert mr.verdict(ok, cf, True, True)[0] == "con evidencia"
    assert mr.verdict(ok, cf, False, True)[0] == "sin evidencia suficiente"          # no se sostiene en BTC+ETH
    assert mr.verdict(ok, cf, True, False)[0] == "sin evidencia suficiente"          # depende de un año
    assert mr.verdict({**ok, "p": 0.01}, cf, True, True)[0] == "sin evidencia suficiente"   # no pasa Bonferroni
    assert mr.verdict(ok, {**cf, "exceso": -0.04}, True, True)[0] == "sin evidencia suficiente"
    assert mr.verdict(ok, {**cf, "p": 0.2}, True, True)[0] == "sin evidencia suficiente"
    assert mr.verdict({**ok, "n_episodios_mercado": 9}, cf, True, True)[0] == "sin veredicto"
    assert mr.verdict(ok, {**cf, "n_episodios_mercado": 3}, True, True)[0] == "sin veredicto"
    assert abs(mr.ALPHA_DISC - 0.05 / 24) < 1e-12


def test_run_phase0_on_random_walks_finds_nothing_and_serializes():
    out = mr.run_phase0(_closes(8, 31), n_perm=60)
    n_ev = [out["results"][l][h]["veredicto"] for l in mr.ALL_LABELS for h in mr.HORIZONS]
    assert len(n_ev) == 24 and "con evidencia" not in n_ev
    hoy = out["hoy"]
    assert hoy["fecha"] == "2026-10-31" and len(hoy["monedas"]) == 8 and "aviso" in hoy
    assert set(hoy["historico_por_etiqueta"]) == set(mr.ALL_LABELS)
    s = json.dumps(out, default=lambda o: None if (isinstance(o, float) and not np.isfinite(o)) else str(o))
    assert "min12m" in s
    # control de volatilidad: la volatilidad es persistente
    assert set(out["vol_control"]) == {"vol_baja", "vol_alta"}


def test_descriptives_are_consistent():
    c = _walk(7)
    f = mr.coin_features(c)
    last = f.iloc[-1]
    w = c.iloc[-365:]
    assert abs(last["dist_min"] - (c.iloc[-1] / w.min() - 1)) < 1e-12
    assert abs(last["dist_max"] - (c.iloc[-1] / w.max() - 1)) < 1e-12
    assert abs(last["dd_ath"] - (c.iloc[-1] / c.max() - 1)) < 1e-12
    assert 0 <= last["pct_rank"] <= 1
    assert last["days_since_min"] == len(w) - 1 - int(np.argmin(w.to_numpy()))
