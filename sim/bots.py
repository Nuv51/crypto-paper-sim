"""Bots de estrategia (v1). Numeración = glosario del proyecto:
    #3 DCA · #4 Grid · #5 Reversión a la media · #7 Tendencia/Momentum · #8 Breakout

Contrato de cada bot:
  * prepare(sym, df)  -> agrega columnas de indicadores CAUSALES (sin mirar al futuro).
  * on_bar(ctx)       -> se llama al CIERRE de cada barra; envía órdenes que se llenan desde la barra siguiente.
  * on_fill(fill,ctx) -> se llama cuando una de sus órdenes se ejecuta.
  * Todo el estado dinámico vive en self.st (JSON) para poder pausar/reanudar la simulación.

Todos son spot long-only. Ninguno garantiza rentabilidad: son punto de partida para simular y medir.
"""
from __future__ import annotations

import json
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd

from . import indicators as ind
from .broker import PaperWallet, Fill, floor_qty

HOUR_MS = 3_600_000


class Ctx:
    """Vista de la barra actual: solo pasado y presente, nunca futuro."""

    def __init__(self, ts: int, i: int, wallet: PaperWallet, arrays: dict, bar_ms: int):
        self.ts, self.i, self.wallet, self.arrays, self.bar_ms = ts, i, wallet, arrays, bar_ms

    def v(self, sym: str, col: str, back: int = 0) -> float:
        if back < 0:
            raise ValueError("look-ahead prohibido: `back` debe ser >= 0")
        return float(self.arrays[sym][col][self.i - back])

    def price(self, sym: str) -> float:
        return self.v(sym, "close")

    def equity(self) -> float:
        return self.wallet.equity({s: self.price(s) for s in self.arrays})


def _ok(*xs: float) -> bool:
    return all(not math.isnan(x) for x in xs)


class Bot:
    kind = "base"
    strategy_label = ""
    DEFAULTS: dict = {}

    def __init__(self, spec: dict, bar_ms: int):
        self.id = spec["id"]
        self.name = spec["name"]
        self.exchange = spec["exchange"]
        self.symbols = list(spec["symbols"])
        self.capital = float(spec["capital"])
        self.vol_profile = spec.get("vol_profile", "")
        self.risk_level = spec.get("risk_level", "")
        self.differentiator = spec.get("differentiator", "")
        self.risk = dict(spec.get("risk", {}))
        self.slippage_bps = float(spec.get("slippage_bps", 3.0))
        self.p = SimpleNamespace(**{**self.DEFAULTS, **spec.get("params", {})})
        self.bar_ms = bar_ms
        self.warmup = self._warmup()
        self.st = self.init_state()

    # --- a sobrescribir ---------------------------------------------------------------
    def _warmup(self) -> int:
        return 1

    def init_state(self) -> dict:
        return {}

    def prepare(self, sym: str, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def on_bar(self, ctx: Ctx) -> None:
        raise NotImplementedError

    def on_fill(self, fill: Fill, ctx: Ctx) -> None:
        pass

    def status_detail(self, wallet: PaperWallet) -> str:
        held = [s.replace("USDT", "") for s in self.symbols if wallet.pos(s).qty > 0]
        return f"En posición: {', '.join(held)}" if held else "Esperando señal"

    # --- comunes ----------------------------------------------------------------------
    def reset(self) -> None:
        self.st = self.init_state()

    def on_halt(self, ctx: Ctx) -> None:
        """Cancela todo y liquida (el control de riesgo la llama al romper el drawdown máximo)."""
        ctx.wallet.cancel_all()
        for s in self.symbols:
            self.sell_all(ctx, s, "risk_halt")

    def get_state(self) -> dict:
        return json.loads(json.dumps(self.st))

    def set_state(self, d: dict) -> None:
        self.st = d

    def meta(self) -> dict:
        return dict(bot_id=self.id, name=self.name, strategy=self.strategy_label, exchange=self.exchange,
                    symbols=",".join(self.symbols), vol_profile=self.vol_profile,
                    risk_level=self.risk_level, capital=self.capital,
                    differentiator=self.differentiator,
                    params=json.dumps({**vars(self.p), "_risk": self.risk,
                                       "_slippage_bps": self.slippage_bps}))

    def affordable_quote(self, ctx: Ctx, target: float) -> float:
        q = min(target, ctx.wallet.free_cash() * 0.99)
        return q if q >= ctx.wallet.profile.min_notional * 1.5 else 0.0

    def buy_quote(self, ctx: Ctx, sym: str, quote: float, reason: str, tag: str = ""):
        qty = floor_qty(quote / ctx.price(sym))
        return ctx.wallet.submit(ctx.ts, sym, "buy", "market", qty, reason=reason, tag=tag) if qty > 0 else None

    def sell_all(self, ctx: Ctx, sym: str, reason: str):
        q = ctx.wallet.pos(sym).qty
        return ctx.wallet.submit(ctx.ts, sym, "sell", "market", q, reason=reason) if q > 0 else None

    def n_open(self, ctx: Ctx) -> int:
        held = sum(1 for s in self.symbols if ctx.wallet.pos(s).qty > 0)
        return held + len(ctx.wallet.open_orders(kind="market", side="buy"))


# ======================================================================================
# #3 DCA
# ======================================================================================
class DcaBot(Bot):
    kind = "dca"
    strategy_label = "DCA · compras periódicas de monto fijo"
    DEFAULTS = dict(interval_hours=72, contribution_pct=0.025)

    def init_state(self) -> dict:
        return {"last_buy_ts": 0, "n_buys": 0, "invested": 0.0, "exhausted": False}

    def on_bar(self, ctx: Ctx) -> None:
        p, st = self.p, self.st
        if st["last_buy_ts"] and ctx.ts - st["last_buy_ts"] < p.interval_hours * HOUR_MS:
            return
        total = ctx.wallet.initial_cash * p.contribution_pct
        if ctx.wallet.free_cash() < total * 1.01:
            st["exhausted"] = True
            return
        for s in self.symbols:
            self.buy_quote(ctx, s, total / len(self.symbols), "dca")
        st["last_buy_ts"] = ctx.ts
        st["n_buys"] += 1
        st["invested"] += total

    def status_detail(self, wallet: PaperWallet) -> str:
        if self.st["exhausted"]:
            return f"Capital agotado tras {self.st['n_buys']} compras"
        return f"{self.st['n_buys']} compras · {self.st['invested']:,.0f} USDT invertidos"


# ======================================================================================
# #4 Grid
# ======================================================================================
class GridBot(Bot):
    """Grid spot de una sola moneda. Arranca con todo el capital en efectivo: coloca compras límite
    por debajo del precio y, cuando una se llena, coloca la venta un nivel arriba (ping-pong).
    Protección: si el precio rompe el rango, liquida (abajo) o re-centra (arriba)."""
    kind = "grid"
    strategy_label = "Grid · órdenes límite escalonadas en un rango"
    DEFAULTS = dict(range_pct=0.10, n_levels=16, capital_use=0.95, stop_buffer=0.02,
                    recenter_wait_bars=72)

    def __init__(self, spec: dict, bar_ms: int):
        super().__init__(spec, bar_ms)
        if len(self.symbols) != 1:
            raise ValueError("GridBot opera una sola moneda")
        self.sym = self.symbols[0]

    def init_state(self) -> dict:
        return {"built": False, "levels": [], "quote_each": 0.0, "lower": 0.0, "upper": 0.0,
                "wait_until": 0, "cycles": 0, "note": "Aún sin grid"}

    def _build(self, ctx: Ctx) -> None:
        g, p = self.st, self.p
        px = ctx.price(self.sym)
        n = int(p.n_levels)
        levels = [px * (1 - p.range_pct) + 2 * p.range_pct * px * k / n for k in range(n + 1)]
        below = [k for k, lv in enumerate(levels) if lv < px * 0.9995]
        if not below:
            return
        base = min(ctx.wallet.initial_cash, ctx.wallet.free_cash())
        quote_each = base * p.capital_use / len(below)
        g.update(built=True, levels=levels, quote_each=quote_each, lower=levels[0], upper=levels[-1],
                 note=f"Grid activo: {n} niveles")
        for k in below:
            qty = floor_qty(quote_each / levels[k])
            ctx.wallet.submit(ctx.ts, self.sym, "buy", "limit", qty, price=levels[k],
                              tag=f"B{k}", reason="grid_buy")

    def on_fill(self, fill: Fill, ctx: Ctx) -> None:
        g = self.st
        if fill.symbol != self.sym or not fill.tag or not g["built"]:
            return
        k, lv = int(fill.tag[1:]), g["levels"]
        if fill.tag[0] == "B" and k + 1 < len(lv):
            ctx.wallet.submit(ctx.ts, self.sym, "sell", "limit", fill.qty, price=lv[k + 1],
                              tag=f"S{k + 1}", reason="grid_sell")
        elif fill.tag[0] == "S" and k - 1 >= 0:
            g["cycles"] += 1
            qty = floor_qty(g["quote_each"] / lv[k - 1])
            ctx.wallet.submit(ctx.ts, self.sym, "buy", "limit", qty, price=lv[k - 1],
                              tag=f"B{k - 1}", reason="grid_buy")

    def on_bar(self, ctx: Ctx) -> None:
        g, p, w = self.st, self.p, ctx.wallet
        close = ctx.price(self.sym)
        if g["built"]:
            if close < g["lower"] * (1 - p.stop_buffer):
                w.cancel_all()
                self.sell_all(ctx, self.sym, "grid_break_down")
                g.update(built=False, wait_until=ctx.ts + int(p.recenter_wait_bars) * self.bar_ms,
                         note="Ruptura bajista: liquidado, espera para re-centrar")
            elif close > g["upper"] * (1 + p.stop_buffer):
                w.cancel_all()
                self.sell_all(ctx, self.sym, "grid_break_up")
                g.update(built=False, wait_until=ctx.ts, note="Ruptura alcista: re-centrando")
        elif ctx.ts >= g["wait_until"] and w.pos(self.sym).qty <= 0 and not w.open_orders(kind="market"):
            self._build(ctx)

    def on_halt(self, ctx: Ctx) -> None:
        super().on_halt(ctx)
        self.st.update(built=False, wait_until=2 ** 62, note="Detenido por el control de riesgo")

    def status_detail(self, wallet: PaperWallet) -> str:
        g = self.st
        if g["built"]:
            return f"Grid {len(g['levels']) - 1} niveles [{g['lower']:,.2f}–{g['upper']:,.2f}] · {g['cycles']} ciclos"
        return g["note"]


# ======================================================================================
# #5 Reversión a la media
# ======================================================================================
class MeanReversionBot(Bot):
    kind = "meanrev"
    strategy_label = "Reversión a la media · RSI + Bandas de Bollinger"
    DEFAULTS = dict(rsi_n=14, rsi_buy=30, bb_n=20, bb_k=2.0, atr_n=14, atr_mult=1.5,
                    stop_min=0.02, stop_max=0.03, tp_pct=0.04, max_positions=2,
                    max_hold_bars=72, cooldown_bars=6, exit_at_mid=True, require_green=True,
                    size_frac=0.95)

    def _warmup(self) -> int:
        return int(5 * max(self.p.rsi_n, self.p.bb_n, self.p.atr_n)) + 5

    def init_state(self) -> dict:
        return {s: {"entry": 0.0, "stop": 0.0, "tp": 0.0, "bars": 0, "cooldown_until": 0,
                    "pending_atr_pct": 0.0} for s in self.symbols}

    def prepare(self, sym: str, df: pd.DataFrame) -> pd.DataFrame:
        p, out = self.p, df.copy()
        out["rsi"] = ind.rsi(df["close"], p.rsi_n)
        out["bb_mid"], out["bb_up"], out["bb_lo"] = ind.bollinger(df["close"], p.bb_n, p.bb_k)
        out["atr"] = ind.atr(df, p.atr_n)
        return out

    def on_fill(self, fill: Fill, ctx: Ctx) -> None:
        st, p = self.st[fill.symbol], self.p
        if fill.side == "buy":
            sd = min(max(p.atr_mult * st["pending_atr_pct"], p.stop_min), p.stop_max)
            st.update(entry=fill.price, stop=fill.price * (1 - sd), tp=fill.price * (1 + p.tp_pct), bars=0)
        elif ctx.wallet.pos(fill.symbol).qty <= 0:
            st["cooldown_until"] = fill.ts + int(p.cooldown_bars) * self.bar_ms

    def on_bar(self, ctx: Ctx) -> None:
        p, w = self.p, ctx.wallet
        for s in self.symbols:
            st, close = self.st[s], ctx.price(s)
            if w.pos(s).qty > 0:
                st["bars"] += 1
                reason = None
                if close <= st["stop"]:
                    reason = "stop"
                elif close >= st["tp"]:
                    reason = "take_profit"
                elif p.exit_at_mid and close >= ctx.v(s, "bb_mid"):
                    reason = "mean_reached"
                elif st["bars"] >= p.max_hold_bars:
                    reason = "time_stop"
                if reason:
                    self.sell_all(ctx, s, reason)
                continue
            if ctx.ts < st["cooldown_until"] or self.n_open(ctx) >= p.max_positions:
                continue
            r, lo, a, op = ctx.v(s, "rsi"), ctx.v(s, "bb_lo"), ctx.v(s, "atr"), ctx.v(s, "open")
            if not _ok(r, lo, a):
                continue
            if r < p.rsi_buy and close <= lo and (not p.require_green or close > op):
                q = self.affordable_quote(ctx, w.initial_cash * p.size_frac / p.max_positions)
                if q > 0:
                    st["pending_atr_pct"] = a / close
                    self.buy_quote(ctx, s, q, "rsi_bb_oversold")


# ======================================================================================
# #7 Tendencia / Momentum
# ======================================================================================
class TrendBot(Bot):
    kind = "trend"
    strategy_label = "Tendencia · cruce de EMAs + momentum, trailing stop"
    DEFAULTS = dict(fast=24, slow=96, roc_n=72, stop_pct=0.04, trail_start=0.05,
                    trail_margin=0.025, cooldown_bars=24, size_frac=0.95)

    def _warmup(self) -> int:
        return int(max(self.p.slow * 3, self.p.roc_n)) + 10

    def init_state(self) -> dict:
        return {s: {"entry": 0.0, "high": 0.0, "cooldown_until": 0} for s in self.symbols}

    def prepare(self, sym: str, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out["ema_f"] = ind.ema(df["close"], self.p.fast)
        out["ema_s"] = ind.ema(df["close"], self.p.slow)
        out["roc"] = ind.roc(df["close"], self.p.roc_n)
        return out

    def on_fill(self, fill: Fill, ctx: Ctx) -> None:
        st = self.st[fill.symbol]
        if fill.side == "buy":
            st.update(entry=fill.price, high=fill.price)
        elif ctx.wallet.pos(fill.symbol).qty <= 0:
            st["cooldown_until"] = fill.ts + int(self.p.cooldown_bars) * self.bar_ms

    def on_bar(self, ctx: Ctx) -> None:
        p, w = self.p, ctx.wallet
        for s in self.symbols:
            st, close = self.st[s], ctx.price(s)
            ef, es, rc = ctx.v(s, "ema_f"), ctx.v(s, "ema_s"), ctx.v(s, "roc")
            if not _ok(ef, es, rc):
                continue
            if w.pos(s).qty > 0:
                st["high"] = max(st["high"], close)
                reason = None
                if close <= st["entry"] * (1 - p.stop_pct):
                    reason = "stop"
                elif st["high"] >= st["entry"] * (1 + p.trail_start) and close <= st["high"] * (1 - p.trail_margin):
                    reason = "trailing_stop"
                elif ef < es:
                    reason = "trend_end"
                if reason:
                    self.sell_all(ctx, s, reason)
            elif ctx.ts >= st["cooldown_until"] and ef > es and close > es and rc > 0:
                q = self.affordable_quote(ctx, w.initial_cash * p.size_frac / len(self.symbols))
                if q > 0:
                    self.buy_quote(ctx, s, q, "trend_up")


# ======================================================================================
# #8 Breakout con riesgo dinámico
# ======================================================================================
class BreakoutBot(Bot):
    kind = "breakout"
    strategy_label = "Breakout · ruptura de canal Donchian con stop ATR y sizing por riesgo"
    DEFAULTS = dict(entry_n=48, exit_n=24, atr_n=14, atr_mult=1.75, vol_n=48, vol_mult=1.5,
                    risk_pct=0.0075, max_pos_frac=0.5, fail_bars=4, cooldown_bars=12)

    def _warmup(self) -> int:
        return int(max(self.p.entry_n, self.p.exit_n, self.p.vol_n, 5 * self.p.atr_n)) + 5

    def init_state(self) -> dict:
        return {s: {"entry": 0.0, "stop": 0.0, "level": 0.0, "bars": 0, "cooldown_until": 0,
                    "pending_stop_dist": 0.0, "pending_level": 0.0} for s in self.symbols}

    def prepare(self, sym: str, df: pd.DataFrame) -> pd.DataFrame:
        p, out = self.p, df.copy()
        out["don_hi"] = ind.donchian_high(df, p.entry_n)
        out["don_lo"] = ind.donchian_low(df, p.exit_n)
        out["atr"] = ind.atr(df, p.atr_n)
        out["vol_ma"] = df["volume"].rolling(p.vol_n, min_periods=p.vol_n).mean().shift(1)
        return out

    def on_fill(self, fill: Fill, ctx: Ctx) -> None:
        st = self.st[fill.symbol]
        if fill.side == "buy":
            st.update(entry=fill.price, stop=fill.price - st["pending_stop_dist"],
                      level=st["pending_level"], bars=0)
        elif ctx.wallet.pos(fill.symbol).qty <= 0:
            st["cooldown_until"] = fill.ts + int(self.p.cooldown_bars) * self.bar_ms

    def on_bar(self, ctx: Ctx) -> None:
        p, w = self.p, ctx.wallet
        for s in self.symbols:
            st, close = self.st[s], ctx.price(s)
            if w.pos(s).qty > 0:
                st["bars"] += 1
                reason = None
                if close <= st["stop"]:
                    reason = "stop_atr"
                elif st["bars"] <= p.fail_bars and close < st["level"]:
                    reason = "false_breakout"
                elif close < ctx.v(s, "don_lo"):
                    reason = "channel_exit"
                if reason:
                    self.sell_all(ctx, s, reason)
                continue
            if ctx.ts < st["cooldown_until"]:
                continue
            hi, a, vol, vma = ctx.v(s, "don_hi"), ctx.v(s, "atr"), ctx.v(s, "volume"), ctx.v(s, "vol_ma")
            if not _ok(hi, a, vma) or a <= 0:
                continue
            if close > hi and vol > p.vol_mult * vma:
                stop_dist = p.atr_mult * a
                qty = min(p.risk_pct * ctx.equity() / stop_dist,           # riesgo fijo por operación
                          p.max_pos_frac * w.initial_cash / close,          # tope de tamaño
                          w.free_cash() * 0.99 / close)
                qty = floor_qty(qty)
                if qty * close >= w.profile.min_notional * 1.5:
                    st.update(pending_stop_dist=stop_dist, pending_level=hi)
                    w.submit(ctx.ts, s, "buy", "market", qty, reason="donchian_breakout")


BOT_CLASSES = {"dca": DcaBot, "grid": GridBot, "meanrev": MeanReversionBot,
               "trend": TrendBot, "breakout": BreakoutBot}


def build_bot(spec: dict, bar_ms: int) -> Bot:
    try:
        return BOT_CLASSES[spec["kind"]](spec, bar_ms)
    except KeyError as e:
        raise KeyError(f"Tipo de bot desconocido: {spec.get('kind')}") from e
