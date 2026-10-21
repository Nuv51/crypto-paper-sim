"""Pruebas del simulador indexado: pesos con tope, compra inicial, rebalanceo en dos tiempos, estado entre corridas.

Ejecuta:  python -m pytest -q   (las pruebas no usan fixtures: también corren con un ejecutor simple)
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config_index  # noqa: E402
from sim.bots import build_bot  # noqa: E402
import sim.cloud as cloud  # noqa: E402
from sim.cloud import config_signature, run_step  # noqa: E402
from sim.engine import Engine  # noqa: E402
from sim.indexing import capped_weights, index_weights  # noqa: E402
from sim.ledger import Ledger, read_only_connection  # noqa: E402
from sim.metrics import load_all  # noqa: E402

cloud.fetch_fear_greed = lambda session=None: None          # las pruebas no tocan la red

H = 3_600_000
SYMS = ["AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT", "EEEUSDT", "FFFUSDT"]
CAPS = {"AAAUSDT": 600e9, "BBBUSDT": 200e9, "CCCUSDT": 100e9, "DDDUSDT": 60e9, "EEEUSDT": 30e9, "FFFUSDT": 10e9}


def _tmp() -> Path:
    return Path(tempfile.mkdtemp(prefix="idx_"))


def mini_cfg(weighting="cap", **over):
    params = dict(weighting=weighting, cap_max=0.40, rebalance_hours=48, cash_buffer=0.005, min_trade_usdt=8.0, min_weight=0.0008)
    params.update(over)
    return dict(id="i99_index_t", kind="index", name="t", exchange="binance", symbols=list(SYMS), caps_usd=dict(CAPS),
                slippage_map_bps={s: 5 for s in SYMS}, slippage_bps=10, capital_pct=1.0, risk_level="medio",
                params=params, risk=dict(max_drawdown=0.5, action="flag_only"))


def frames(n=200, drift=None, seed=3):
    """Series casi planas con ruido mínimo; `drift` = {símbolo: factor total al final} para forzar que una moneda se aleje."""
    rng = np.random.default_rng(seed)
    out = {}
    for i, s in enumerate(SYMS):
        base = 10.0 * (i + 1)
        path = base * np.exp(np.cumsum(rng.normal(0, 0.0005, n)))
        if drift and s in drift:
            path = path * np.linspace(1.0, drift[s], n)
        o = np.concatenate([[path[0]], path[:-1]])
        out[s] = pd.DataFrame({"open": o, "high": np.maximum(o, path) * 1.0005, "low": np.minimum(o, path) * 0.9995,
                               "close": path, "volume": np.full(n, 1000.0)},
                              index=pd.Index(np.arange(n, dtype="int64") * H, name="ts"))
    return out


def replay(cfg, fr, capital=10_000.0):
    d = _tmp()
    ledger = Ledger(d / "x.db")
    eng = Engine(ledger, [cfg], capital, "1h", portfolio_risk=dict(max_drawdown=None, cooldown_bars=168))
    eng.replay(fr, progress=None)
    ledger.close()
    return eng, load_all(read_only_connection(d / "x.db"))


def weights_held(eng):
    rt = eng.runtimes["i99_index_t"]
    last = {s: float(rt.last_marks[s]) for s in SYMS}
    vals = {s: rt.wallet.pos(s).qty * last[s] for s in SYMS}
    tot = rt.wallet.cash + sum(vals.values())
    return {s: v / tot for s, v in vals.items()}, rt.wallet.cash / tot, tot


# ---------------------------------------------------------------------------------- pesos
def test_capped_weights_sum_cap_and_redistribution():
    w = capped_weights({"a": 70, "b": 20, "c": 5, "d": 5}, 0.30)
    assert abs(sum(w.values()) - 1) < 1e-12
    assert abs(w["a"] - 0.30) < 1e-12 and abs(w["b"] - 0.30) < 1e-12        # b también se topa al recibir el exceso de a
    assert abs(w["c"] - w["d"]) < 1e-12 and abs(w["c"] - 0.20) < 1e-12
    assert all(x <= 0.30 + 1e-12 for x in w.values())


def test_capped_weights_without_cap_is_proportional_and_infeasible_cap_raises():
    w = capped_weights({"a": 3, "b": 1}, None)
    assert abs(w["a"] - 0.75) < 1e-12 and abs(w["b"] - 0.25) < 1e-12
    try:
        capped_weights({"a": 1, "b": 1, "c": 1}, 0.30)
        raise AssertionError("debió fallar: 3 monedas con tope 30 % no suman 100 %")
    except ValueError:
        pass


def test_capped_weights_keeps_order_between_uncapped():
    w = capped_weights({"a": 90, "b": 6, "c": 3, "d": 1}, 0.50)
    assert w["a"] == 0.50 and w["b"] > w["c"] > w["d"] > 0
    assert abs(sum(w.values()) - 1) < 1e-12


def test_index_weights_drops_tiny_positions_and_renormalizes():
    raw = {"a": 1000.0, "b": 500.0, "c": 400.0, "d": 300.0, "e": 0.2}
    w = index_weights(raw, 0.5, min_weight=0.001)
    assert "e" not in w and abs(sum(w.values()) - 1) < 1e-12 and max(w.values()) <= 0.5 + 1e-12
    assert index_weights({}, 0.3, 0.001) == {}


def test_equal_weight_is_equal():
    w = index_weights({s: 1.0 for s in SYMS}, None, 0.0008)
    assert all(abs(x - 1 / 6) < 1e-12 for x in w.values())


# ---------------------------------------------------------------------------------- bot
def test_initial_buy_matches_target_weights_and_keeps_buffer():
    eng, data = replay(mini_cfg(rebalance_hours=10_000), frames(20))
    w, cash_frac, tot = weights_held(eng)
    expected = capped_weights({s: CAPS[s] for s in SYMS}, 0.40)                  # precios ~ iguales al inicio -> pesos ≈ caps
    # el suministro implícito fija los pesos iniciales a la capitalización dada (hasta el ruido del primer precio)
    for s in SYMS:
        assert abs(w[s] - expected[s]) < 0.01, (s, w[s], expected[s])
    assert 0.003 < cash_frac < 0.02                                             # colchón 0.5 % menos costos
    trades = data["trades"]
    assert (trades.side == "buy").all() and len(trades) == len(SYMS)
    assert (trades.reason == "index_init").all()
    assert tot < 10_000 and tot > 9_950                                         # solo costó comisión + deslizamiento


def test_cap_weights_respect_cap_in_portfolio():
    eng, _ = replay(mini_cfg(cap_max=0.30), frames(20))
    w, _, _ = weights_held(eng)
    assert max(w.values()) <= 0.30 + 0.01
    assert w["AAAUSDT"] > 0.28


def test_equal_weight_portfolio():
    eng, _ = replay(mini_cfg("equal"), frames(20))
    w, _, _ = weights_held(eng)
    assert max(w.values()) - min(w.values()) < 0.01


def test_rebalance_sells_first_then_buys_and_restores_weights():
    # AAA se triplica: sin rebalanceo su peso se dispararía; con rebalanceo mensual debe volver cerca del objetivo
    fr = frames(260, drift={"AAAUSDT": 3.0})
    eng, data = replay(mini_cfg(rebalance_hours=48, cap_max=0.40), fr)
    t = data["trades"]
    reb = t[t.reason == "index_rebalance"]
    assert not reb.empty and (reb.side == "sell").any() and (reb.side == "buy").any()
    # en cada rebalanceo, las ventas se ejecutan en una vela anterior a las compras
    for _, grp in reb.groupby((reb.ts // (48 * H))):
        sells, buys = grp[grp.side == "sell"], grp[grp.side == "buy"]
        if len(sells) and len(buys):
            assert sells.ts.max() < buys.ts.min()
    st = eng.runtimes["i99_index_t"].bot.st
    assert st["n_rebalances"] >= 3
    w, cash_frac, _ = weights_held(eng)
    assert w["AAAUSDT"] < 0.46                                                  # sin rebalanceo estaría por encima de 0.7
    assert cash_frac < 0.03


def test_no_trades_between_rebalances_when_nothing_drifts():
    fr = frames(100)
    _, data = replay(mini_cfg(rebalance_hours=10_000), fr)
    assert len(data["trades"]) == len(SYMS)                                     # solo la compra inicial


def test_fees_and_slippage_are_charged():
    eng, data = replay(mini_cfg(rebalance_hours=10_000), frames(5))
    t = data["trades"]
    assert (t.fee > 0).all()
    assert abs(t.fee.sum() - 0.001 * t.notional.sum()) < 1e-6                  # taker de Binance 0.10 %


def test_bot_state_roundtrip_json():
    eng, _ = replay(mini_cfg(), frames(120))
    bot = eng.runtimes["i99_index_t"].bot
    st = bot.get_state()
    assert json.loads(json.dumps(st)) == st and set(st["supply"]) == set(SYMS)


def test_missing_caps_or_bad_cap_rejected():
    c = mini_cfg()
    c["caps_usd"].pop("FFFUSDT")
    for bad in (c, mini_cfg(cap_max=0.10), mini_cfg(weighting="otra")):
        try:
            build_bot(dict(bad, capital=1000.0), H)
            raise AssertionError("debió rechazar la configuración")
        except ValueError:
            pass


# ---------------------------------------------------------------------------------- configuración real
def test_config_index_is_consistent():
    c = config_index
    assert len(c.UNIVERSE_SYMBOLS) == 50 == len(set(c.UNIVERSE_SYMBOLS)) and c.TOP25 == c.UNIVERSE_SYMBOLS[:25]
    caps = [c.CAPS_USD[s] for s in c.UNIVERSE_SYMBOLS]
    assert caps == sorted(caps, reverse=True)
    assert all(s.endswith("USDT") and s in c.SLIPPAGE_BPS for s in c.UNIVERSE_SYMBOLS)
    assert abs(sum(b["capital_pct"] for b in c.BOTS) - 1) < 1e-12 and len(c.BOTS) == 3
    for b in c.BOTS:
        bot = build_bot(dict(b, capital=c.PORTFOLIO_CAPITAL * b["capital_pct"]), H)
        assert abs(bot.capital - 10_000) < 1e-6
    stable = {"USDTUSDT", "USDCUSDT", "FDUSDUSDT", "DAIUSDT", "USDEUSDT", "XAUTUSDT", "PAXGUSDT"}
    assert not stable & set(c.UNIVERSE_SYMBOLS)
    # los tres bots usan los pesos descritos
    w25 = index_weights({s: c.CAPS_USD[s] for s in c.TOP25}, 0.30, 0.0008)
    w50 = index_weights({s: c.CAPS_USD[s] for s in c.TOP50}, 0.30, 0.0008)
    assert max(w25.values()) <= 0.30 + 1e-12 and max(w50.values()) <= 0.30 + 1e-12
    assert abs(sum(w25.values()) - 1) < 1e-12 and abs(sum(w50.values()) - 1) < 1e-12
    assert len(w25) == 25 and 25 < len(w50) <= 50


def test_config_signature_changes_with_universe():
    c = config_index
    a = config_signature(c.BOTS, c.PORTFOLIO_CAPITAL, c.PORTFOLIO_RISK)
    other = copy.deepcopy(c.BOTS)
    other[0]["params"]["cap_max"] = 0.25
    assert a != config_signature(other, c.PORTFOLIO_CAPITAL, c.PORTFOLIO_RISK)


# ---------------------------------------------------------------------------------- nube
class FakeFeed:
    """Entrega las velas hasta `upto` horas; así se simulan corridas sucesivas en sesiones nuevas."""
    label = "Mercado real (Binance · KuCoin · Bitso, APIs públicas)"
    pause = 0

    def __init__(self, fr, upto):
        self.fr, self.upto = fr, upto

    def latest_closed(self, sym, interval, n):
        return self.fr[sym].iloc[: self.upto].tail(n)


def _cloud_cfg():
    c = mini_cfg(rebalance_hours=12)
    return [c]


def test_cloud_runs_in_batches_equal_one_run():
    fr = frames(120, drift={"AAAUSDT": 2.5, "FFFUSDT": 0.5})
    cfgs = _cloud_cfg()
    d = _tmp()
    code, _ = run_step(cfgs, "1h", 10_000.0, None, str(d / "a"), "binance", feed=FakeFeed(fr, 60),
                       portfolio_risk=dict(max_drawdown=None, cooldown_bars=168), window=400, keep_bars=400)
    assert code == 0
    # sesión nueva con las horas 61..90 de una sola vez
    code, st = run_step(cfgs, "1h", 10_000.0, str(d / "a" / "ledger.json"), str(d / "b"), "binance", feed=FakeFeed(fr, 90),
                        portfolio_risk=dict(max_drawdown=None, cooldown_bars=168), window=400, keep_bars=400)
    assert code == 0 and st["resumed"]
    # vela por vela desde la primera corrida
    prev = str(d / "a" / "ledger.json")
    for k in range(61, 91):
        code, _ = run_step(cfgs, "1h", 10_000.0, prev, str(d / f"s{k}"), "binance", feed=FakeFeed(fr, k),
                           portfolio_risk=dict(max_drawdown=None, cooldown_bars=168), window=400, keep_bars=400)
        assert code == 0
        prev = str(d / f"s{k}" / "ledger.json")
    one = json.loads((d / "b" / "ledger.json").read_text())
    many = json.loads(Path(prev).read_text())
    s1 = json.loads(one["bot_state"][0]["state"]) if isinstance(one.get("bot_state"), list) else one["bot_state"]
    s2 = json.loads(many["bot_state"][0]["state"]) if isinstance(many.get("bot_state"), list) else many["bot_state"]
    assert s1 == s2


def test_dashboard_has_index_family():
    fr = frames(120)
    d = _tmp()
    code, _ = run_step(_cloud_cfg(), "1h", 10_000.0, None, str(d / "a"), "binance", feed=FakeFeed(fr, 100),
                       portfolio_risk=dict(max_drawdown=None, cooldown_bars=168), window=400, keep_bars=400,
                       sim=dict(id="indice", name="Simulador indexado", other="binance", desc="x"))
    assert code == 0
    dash = json.loads((d / "a" / "dashboard.json").read_text())
    assert dash["sim"]["id"] == "indice" and dash["families"][0]["key"] == "indice"
    assert dash["bots"][0]["family"] == "indice" and dash["portfolio_risk"] is None
