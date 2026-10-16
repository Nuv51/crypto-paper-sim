"""Bots de estrategia. Numeración = glosario del proyecto:
    #1 Carry spot-perpetuo · #2 Stablecoins · #3 DCA · #4 Grid · #5 Reversión a la media · #6 Market making
    #7 Tendencia/Momentum · #8 Breakout · #9 ML · #10 Arbitraje cross-exchange vía XRP

Contrato de cada bot:
  * prepare(sym, df)  -> agrega columnas de indicadores CAUSALES (sin mirar al futuro).
  * on_bar(ctx)       -> se llama al CIERRE de cada barra; envía órdenes que se llenan desde la barra siguiente.
  * on_fill(fill,ctx) -> se llama cuando una de sus órdenes se ejecuta.
  * mark(ctx,rows)    -> (opcional) patas fuera de la cartera spot, antes de valorar la barra (perpetuo, funding).
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

    def mark(self, ctx: Ctx, rows: dict) -> None:
        """Se llama en CADA barra (incluso si el bot está pausado/detenido), después de las órdenes spot y antes
        de valorar. rows[sym] = (open, high, low, close) de la barra actual."""

    def exposure(self, wallet: PaperWallet) -> dict:
        """Cantidad neta que el bot tiene expuesta al precio de cada mercado real (largos spot; los cortos restan).
        Sirve para separar cuánto del cambio de equity lo puso el mercado y cuánto las decisiones del bot."""
        return {s: wallet.pos(s).qty for s in self.symbols if "~" not in s and wallet.pos(s).qty > 0}

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


# ======================================================================================
# #1 Carry spot-perpetuo (cash & carry / funding rate)
# ======================================================================================
class CarryBot(Bot):
    """Largo spot + corto del perpetuo del mismo activo (delta-neutral): cobra el funding cuando es positivo.

    Qué se simula: la pata spot pasa por el wallet (comisión taker + slippage). La pata corta del perpetuo se
    registra con `wallet.book` (comisión taker del perp + slippage), se valora cada barra con el precio del
    perpetuo y cobra el funding en cada liquidación SOLO si estaba abierta desde una barra anterior
    (si abre o cierra justo en la barra de liquidación no cobra: criterio conservador).
    La garantía (margen) no se descuenta del efectivo: es dinero propio que sigue en la cuenta; solo se limita
    el tamaño de la posición para que quede margen de sobra.
    """
    kind = "carry"
    strategy_label = "Carry · largo spot + corto perpetuo (delta-neutral), cobra funding"
    DEFAULTS = dict(perp_taker=0.0006, perp_slip_bps=2.0, leverage=2.0, avg_n=3, min_apr=0.05,
                    min_hold_days=10, neg_periods_exit=3, margin_stress=0.8, size_frac=0.95)

    def __init__(self, spec: dict, bar_ms: int):
        super().__init__(spec, bar_ms)
        spot = [s for s in self.symbols if "~" not in s]
        perp = [s for s in self.symbols if s.endswith("~PERP")]
        if len(spot) != 1 or len(perp) != 1:
            raise ValueError("CarryBot necesita exactamente un símbolo spot y uno ~PERP")
        self.spot, self.perp = spot[0], perp[0]

    def _warmup(self) -> int:
        return 60

    def init_state(self) -> dict:
        return {"phase": "flat", "open_req": False, "close_req": False, "close_reason": "",
                "perp_qty": 0.0, "perp_entry": 0.0, "perp_ts": 0, "entered_ts": 0,
                "funding_total": 0.0, "n_funding": 0, "note": "Sin datos de funding todavía"}

    # --- helpers -----------------------------------------------------------------------
    def _recent_rates(self, ctx: Ctx, n: int) -> list:
        arr = ctx.arrays[self.perp]["funding"][max(0, ctx.i - 60): ctx.i + 1]
        vals = arr[~np.isnan(arr)]
        return [float(x) for x in vals[-n:]]

    def _cost_roundtrip(self, ctx: Ctx) -> float:
        spot = ctx.wallet.profile.taker + self.slippage_bps / 1e4
        perp = self.p.perp_taker + self.p.perp_slip_bps / 1e4
        return 2 * spot + 2 * perp

    def _request_close(self, ctx: Ctx, reason: str) -> None:
        self.sell_all(ctx, self.spot, reason)
        self.st.update(close_req=True, close_reason=reason, phase="closing", open_req=False)

    # --- patas fuera de spot -----------------------------------------------------------
    def mark(self, ctx: Ctx, rows: dict) -> None:
        st, w, p, ts = self.st, ctx.wallet, self.p, ctx.ts
        o, _, _, c = rows[self.perp]
        rate = float(ctx.arrays[self.perp]["funding"][ctx.i])
        slip = p.perp_slip_bps / 1e4
        held_before = st["perp_qty"] > 0 and st["perp_ts"] < ts

        if st["close_req"]:                                   # 1) cierre del corto (compra a mercado)
            q = st["perp_qty"]
            if q > 0:
                px = o * (1 + slip)
                fee = q * px * p.perp_taker
                gross = q * (st["perp_entry"] - px)
                w.book(ts, self.perp, "sell", "perp", q, px, fee=fee, realized=gross - fee,
                       reason=st["close_reason"] or "carry_close")
                st.update(perp_qty=0.0, perp_entry=0.0)
            st.update(close_req=False, phase="flat", note="Cerrado; esperando funding atractivo")
            held_before = False

        if held_before and not math.isnan(rate):              # 2) funding (el corto cobra si rate > 0)
            q = st["perp_qty"]
            pay = q * o * rate
            w.book(ts, self.perp, "sell", "funding", q, o, fee=0.0, realized=pay, reason="funding")
            st["funding_total"] += pay
            st["n_funding"] += 1

        if st["open_req"]:                                    # 3) apertura del corto = lo que se compró en spot
            st["open_req"] = False
            q = floor_qty(w.pos(self.spot).qty)
            if q > 0 and st["perp_qty"] == 0:
                px = o * (1 - slip)
                fee = q * px * p.perp_taker
                w.book(ts, self.perp, "buy", "perp", q, px, fee=fee, realized=-fee, reason="carry_open")
                st.update(perp_qty=q, perp_entry=px, perp_ts=ts, entered_ts=ts, phase="open")
            elif st["perp_qty"] == 0:
                st["phase"] = "flat"

        q = st["perp_qty"]                                    # 4) P&L no realizado del corto
        w.extra_value = q * (st["perp_entry"] - c) if q > 0 else 0.0

    # --- decisiones ----------------------------------------------------------------------
    def on_bar(self, ctx: Ctx) -> None:
        st, p, w = self.st, self.p, ctx.wallet
        if st["open_req"] or st["close_req"] or st["phase"] in ("opening", "closing"):
            return
        rates = self._recent_rates(ctx, max(p.avg_n, p.neg_periods_exit))
        if st["perp_qty"] > 0:
            margin = st["perp_qty"] * st["perp_entry"] / p.leverage
            loss = st["perp_qty"] * (ctx.price(self.perp) - st["perp_entry"])
            last = rates[-p.neg_periods_exit:]
            if loss >= p.margin_stress * margin:
                self._request_close(ctx, "margin_stress")
            elif len(last) == p.neg_periods_exit and all(r < 0 for r in last):
                self._request_close(ctx, "funding_negative")
            return
        if len(rates) < p.avg_n:
            st["note"] = "Esperando historial de funding"
            return
        avg = sum(rates[-p.avg_n:]) / p.avg_n
        cost = self._cost_roundtrip(ctx)
        hurdle = max(p.min_apr / (3 * 365), cost / (3 * p.min_hold_days))
        apr = avg * 3 * 365
        st["note"] = (f"Esperando: funding {apr:.1%} anual < umbral {hurdle * 3 * 365:.1%} "
                      f"(cubrir costos {cost:.2%} en {p.min_hold_days} días)")
        if avg >= hurdle and all(r > 0 for r in rates[-p.avg_n:]):
            quote = self.affordable_quote(ctx, w.initial_cash * p.size_frac / (1 + 1 / p.leverage))
            if quote > 0 and self.buy_quote(ctx, self.spot, quote, "carry_open"):
                st.update(open_req=True, phase="opening", note=f"Abriendo carry: funding {apr:.1%} anual")

    def exposure(self, wallet: PaperWallet) -> dict:
        e = super().exposure(wallet)
        q = float(self.st.get("perp_qty") or 0.0)
        if q > 0:                                   # el corto en el perpetuo cancela la exposición del spot
            e[self.spot] = e.get(self.spot, 0.0) - q
        return e

    def on_halt(self, ctx: Ctx) -> None:
        super().on_halt(ctx)
        if self.st["perp_qty"] > 0 or self.st["open_req"]:
            self.st.update(close_req=True, close_reason="risk_halt", phase="closing", open_req=False)

    def status_detail(self, wallet: PaperWallet) -> str:
        st = self.st
        if st["perp_qty"] > 0:
            return (f"Carry abierto: {st['perp_qty']:.5f} {self.spot[:-4]} · funding cobrado "
                    f"{st['funding_total']:+,.2f} USDT en {st['n_funding']} liquidaciones")
        if st["n_funding"]:
            return f"{st['note']} · funding acumulado {st['funding_total']:+,.2f} USDT"
        return st["note"]


# ======================================================================================
# #2 Stablecoins / "forex cripto"
# ======================================================================================
class StableBot(Bot):
    """Compra una stablecoin cuando se desvía por DEBAJO de 1.00 USDT y vende al volver al peg.
    Spot long-only: no puede aprovechar desvíos por ENCIMA del peg (haría falta inventario o vender corto)."""
    kind = "stable"
    strategy_label = "Stablecoins · reversión del peg (compra desvíos bajo 1.00, vende al volver)"
    DEFAULTS = dict(entry_dev=0.0030, exit_dev=0.0005, stop_pct=0.010, guard_dev=0.015, depeg=0.020,
                    depeg_bars=6, max_hold_bars=72, cooldown_bars=6, depeg_cooldown_bars=168, size_frac=0.95)

    def init_state(self) -> dict:
        return {s: {"entry": 0.0, "bars": 0, "below": 0, "cooldown_until": 0, "last": 1.0}
                for s in self.symbols}

    def on_fill(self, fill: Fill, ctx: Ctx) -> None:
        st = self.st[fill.symbol]
        if fill.side == "buy":
            st.update(entry=fill.price, bars=0)
        elif ctx.wallet.pos(fill.symbol).qty <= 0:
            wait = self.p.depeg_cooldown_bars if fill.reason == "depeg_exit" else self.p.cooldown_bars
            st["cooldown_until"] = fill.ts + int(wait) * self.bar_ms

    def on_bar(self, ctx: Ctx) -> None:
        p, w = self.p, ctx.wallet
        for s in self.symbols:
            st, close = self.st[s], ctx.price(s)
            dev = 1.0 - close
            st["last"] = close
            st["below"] = st["below"] + 1 if dev >= p.depeg else 0
            if w.pos(s).qty > 0:
                st["bars"] += 1
                reason = None
                if st["below"] >= p.depeg_bars:
                    reason = "depeg_exit"                       # parece un de-peg real: salir, no promediar
                elif close <= st["entry"] * (1 - p.stop_pct):
                    reason = "stop"
                elif close >= 1.0 - p.exit_dev:
                    reason = "peg_restored"
                elif st["bars"] >= p.max_hold_bars:
                    reason = "time_stop"
                if reason:
                    self.sell_all(ctx, s, reason)
            elif ctx.ts >= st["cooldown_until"] and p.entry_dev <= dev < p.guard_dev:
                q = self.affordable_quote(ctx, w.initial_cash * p.size_frac / len(self.symbols))
                if q > 0:
                    self.buy_quote(ctx, s, q, "peg_deviation")

    def status_detail(self, wallet: PaperWallet) -> str:
        held = [s.replace("USDT", "") for s in self.symbols if wallet.pos(s).qty > 0]
        devs = " · ".join(f"{s.replace('USDT', '')} {self.st[s]['last'] - 1:+.3%}" for s in self.symbols)
        return (f"En posición: {', '.join(held)} ({devs})" if held
                else f"Esperando desvío ≥ {self.p.entry_dev:.2%} bajo el peg ({devs})")


# ======================================================================================
# #6 Market making
# ======================================================================================
class MarketMakerBot(Bot):
    """Cotiza compra y venta límite alrededor del precio cada barra, con control de inventario.

    LÍMITE IMPORTANTE: con velas de 1 h no hay libro de órdenes ni prioridad en la cola; un límite se llena si
    el precio lo cruza estrictamente. Es una aproximación que NO sirve para validar un market maker real
    (latencia, selección adversa y cola dominan su resultado)."""
    kind = "mm"
    strategy_label = "Market making · cotiza ±spread/2 con control de inventario"
    DEFAULTS = dict(half_spread=0.0015, quote_frac=0.10, target_inv=0.50, quote_stop_dev=0.20,
                    rebalance_dev=0.30, atr_n=14, vol_guard=0.012)

    def __init__(self, spec: dict, bar_ms: int):
        super().__init__(spec, bar_ms)
        if len(self.symbols) != 1:
            raise ValueError("MarketMakerBot opera una sola moneda")
        self.sym = self.symbols[0]

    def _warmup(self) -> int:
        return int(self.p.atr_n * 5) + 5

    def init_state(self) -> dict:
        return {"init": False, "ratio": 0.5, "buys": 0, "sells": 0, "note": "Sin cotizar aún"}

    def prepare(self, sym: str, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out["atr"] = ind.atr(df, self.p.atr_n)
        return out

    def on_fill(self, fill: Fill, ctx: Ctx) -> None:
        if fill.kind == "limit":
            self.st["buys" if fill.side == "buy" else "sells"] += 1

    def on_bar(self, ctx: Ctx) -> None:
        p, st, w, s = self.p, self.st, ctx.wallet, self.sym
        w.cancel_all(kind="limit")
        px = ctx.price(s)
        if not st["init"]:                                      # inventario inicial: target_inv del capital
            q = self.affordable_quote(ctx, w.initial_cash * p.target_inv)
            if q > 0 and self.buy_quote(ctx, s, q, "mm_init"):
                st["init"], st["note"] = True, "Inventario inicial enviado"
            return
        eq = ctx.equity()
        ratio = w.pos(s).qty * px / eq if eq > 0 else p.target_inv
        dev = ratio - p.target_inv
        st["ratio"] = ratio
        if abs(dev) > p.rebalance_dev:                          # inventario muy desbalanceado: rebalancea a mercado
            excess = (abs(dev) - p.rebalance_dev / 2) * eq
            if dev > 0:
                qty = floor_qty(min(excess / px, w.free_qty(s)))
                if qty > 0:
                    w.submit(ctx.ts, s, "sell", "market", qty, reason="mm_rebalance")
            else:
                q = self.affordable_quote(ctx, excess)
                if q > 0:
                    self.buy_quote(ctx, s, q, "mm_rebalance")
            st["note"] = "Rebalanceando inventario a mercado"
            return
        a = ctx.v(s, "atr")
        if not _ok(a) or a / px > p.vol_guard:
            st["note"] = "Cotización retirada: volatilidad alta"
            return
        hs = p.half_spread
        shift = max(-1.0, min(1.0, dev / 0.5)) * hs * 0.5      # largo -> baja ambas cotizaciones (vende más barato)
        bid, ask = px * (1 - hs - shift), px * (1 + hs - shift)
        qty = floor_qty(p.quote_frac * w.initial_cash / px)
        if dev < p.quote_stop_dev:
            w.submit(ctx.ts, s, "buy", "limit", qty, price=bid, reason="mm_bid", tag="bid")
        if dev > -p.quote_stop_dev:
            sq = floor_qty(min(qty, w.free_qty(s)))
            if sq > 0:
                w.submit(ctx.ts, s, "sell", "limit", sq, price=ask, reason="mm_ask", tag="ask")
        st["note"] = f"Cotizando ±{hs:.2%} alrededor del precio"

    def status_detail(self, wallet: PaperWallet) -> str:
        st = self.st
        return f"{st['note']} · inventario {st['ratio']:.0%} · {st['sells']} ventas / {st['buys']} compras"


# ======================================================================================
# #9 Señales por Machine Learning
# ======================================================================================
def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def fit_logreg(X: np.ndarray, y: np.ndarray, l2: float = 5.0, iters: int = 30) -> np.ndarray:
    """Regresión logística con L2 por Newton (IRLS). Solo numpy: determinista y sin dependencias."""
    n, d = X.shape
    Xb = np.hstack([X, np.ones((n, 1))])
    R = np.eye(d + 1) * l2
    R[-1, -1] = 0.0
    w = np.zeros(d + 1)
    for _ in range(iters):
        p = _sigmoid(Xb @ w)
        g = Xb.T @ (p - y) + R @ w
        H = (Xb * (p * (1 - p) + 1e-6)[:, None]).T @ Xb + R
        step = np.linalg.solve(H, g)
        w -= step
        if np.abs(step).max() < 1e-8:
            break
    return w


class MLBot(Bot):
    """Regresión logística (walk-forward) que estima P(el precio sube en `horizon` horas).

    Se reentrena cada `retrain_bars` con las últimas `train_bars` barras ya CONOCIDAS (la etiqueta de la barra t
    solo se usa cuando t+horizon ya ocurrió). Entra solo si P >= umbral. Registra su acierto FUERA de muestra
    para saber si el modelo sirve o solo parece servir.

    Expectativa honesta: con velas de 1 h el edge predictivo suele ser mínimo; un modelo bien hecho puede pasar
    semanas sin confianza suficiente para operar. Eso también es un resultado válido."""
    kind = "ml"
    strategy_label = "ML · regresión logística walk-forward (P de subida a 6 h)"
    FEATS = ["f_r1", "f_r3", "f_r6", "f_r12", "f_r24", "f_vol24", "f_vratio", "f_rsi", "f_emad", "f_volz", "f_range"]
    DEFAULTS = dict(horizon=6, train_bars=480, retrain_bars=336, thr=0.60, stop_pct=0.03, l2=5.0,
                    min_train=300, cooldown_bars=6, size_frac=0.95)

    def _warmup(self) -> int:
        return int(self.p.train_bars + self.p.horizon + 60)

    def init_state(self) -> dict:
        d = {"w": [], "mu": [], "sd": [], "last_train_ts": 0, "n_train": 0, "n_models": 0,
             "oos_n": 0, "oos_hit": 0, "pend": [], "pmax": 0.0, "n_signals": 0, "last_p": {}}
        for s in self.symbols:
            d[s] = {"entry": 0.0, "bars": 0, "cooldown_until": 0}
        return d

    def prepare(self, sym: str, df: pd.DataFrame) -> pd.DataFrame:
        out, c = df.copy(), df["close"]
        r1 = np.log(c / c.shift(1))
        for n in (1, 3, 6, 12, 24):
            out[f"f_r{n}"] = np.log(c / c.shift(n))
        v24, v6 = r1.rolling(24, min_periods=24).std(), r1.rolling(6, min_periods=6).std()
        out["f_vol24"] = v24
        out["f_vratio"] = v6 / v24.replace(0, np.nan)
        out["f_rsi"] = ind.rsi(c, 14) / 100.0 - 0.5
        out["f_emad"] = c / ind.ema(c, 24) - 1.0
        vol = df["volume"]
        out["f_volz"] = (vol - vol.rolling(48, min_periods=48).mean()) / vol.rolling(48, min_periods=48).std().replace(0, np.nan)
        out["f_range"] = (df["high"] - df["low"]) / c
        return out

    # --- entrenamiento (solo con información conocida hasta la barra actual) ---------------------------------
    def _train(self, ctx: Ctx) -> bool:
        p, h, i = self.p, int(self.p.horizon), ctx.i
        Xs, ys = [], []
        for s in self.symbols:
            a = ctx.arrays[s]
            lo, hi = max(0, i - h - int(p.train_bars) + 1), i - h        # t + h <= i  => etiqueta ya conocida
            if hi <= lo:
                continue
            F = np.column_stack([a[f][lo:hi + 1] for f in self.FEATS])
            fut = a["close"][lo + h:hi + h + 1] / a["close"][lo:hi + 1] - 1.0
            ok = np.isfinite(F).all(axis=1) & np.isfinite(fut)
            Xs.append(F[ok])
            ys.append((fut[ok] > 0).astype(float))
        if not Xs:
            return False
        X, y = np.vstack(Xs), np.concatenate(ys)
        if len(y) < p.min_train or y.min() == y.max():
            return False
        mu, sd = X.mean(axis=0), X.std(axis=0)
        sd[sd == 0] = 1.0
        w = fit_logreg((X - mu) / sd, y, p.l2)
        self.st.update(w=[float(v) for v in w], mu=[float(v) for v in mu], sd=[float(v) for v in sd],
                       last_train_ts=ctx.ts, n_train=int(len(y)), n_models=self.st["n_models"] + 1)
        return True

    def _predict(self, feats: list) -> float:
        st = self.st
        z = (np.array(feats) - np.array(st["mu"])) / np.array(st["sd"])
        return float(_sigmoid(np.dot(z, np.array(st["w"][:-1])) + st["w"][-1]))

    def on_fill(self, fill: Fill, ctx: Ctx) -> None:
        st = self.st[fill.symbol]
        if fill.side == "buy":
            st.update(entry=fill.price, bars=0)
        elif ctx.wallet.pos(fill.symbol).qty <= 0:
            st["cooldown_until"] = fill.ts + int(self.p.cooldown_bars) * self.bar_ms

    def on_bar(self, ctx: Ctx) -> None:
        p, st, w = self.p, self.st, ctx.wallet
        h = int(p.horizon)
        if not st["w"] or ctx.ts - st["last_train_ts"] >= int(p.retrain_bars) * self.bar_ms:
            self._train(ctx)
        keep = []                                                # acierto fuera de muestra de predicciones ya vencidas
        for due, s, pr, px0 in st["pend"]:
            if ctx.ts >= due:
                st["oos_n"] += 1
                st["oos_hit"] += int((pr > 0.5) == (ctx.price(s) / px0 - 1.0 > 0))
            else:
                keep.append([due, s, pr, px0])
        st["pend"] = keep
        if not st["w"]:
            return
        for s in self.symbols:
            feats = [ctx.v(s, f) for f in self.FEATS]
            if not _ok(*feats):
                continue
            pr, close, ss = self._predict(feats), ctx.price(s), st[s]
            st["last_p"][s] = pr
            st["pmax"] = max(st["pmax"], pr)
            st["pend"].append([ctx.ts + h * self.bar_ms, s, pr, close])
            if w.pos(s).qty > 0:
                ss["bars"] += 1
                reason = None
                if close <= ss["entry"] * (1 - p.stop_pct):
                    reason = "stop"
                elif ss["bars"] >= h:
                    reason = "time_stop"
                elif pr < 0.5:
                    reason = "signal_flip"
                if reason:
                    self.sell_all(ctx, s, reason)
            elif pr >= p.thr and ctx.ts >= ss["cooldown_until"]:
                q = self.affordable_quote(ctx, w.initial_cash * p.size_frac / len(self.symbols))
                if q > 0:
                    st["n_signals"] += 1
                    self.buy_quote(ctx, s, q, "ml_signal")

    def status_detail(self, wallet: PaperWallet) -> str:
        st = self.st
        if not st["w"]:
            return "Sin modelo entrenado todavía"
        acc = f"{st['oos_hit'] / st['oos_n']:.0%} ({st['oos_n']} pred.)" if st["oos_n"] else "sin datos aún"
        held = [s.replace("USDT", "") for s in self.symbols if wallet.pos(s).qty > 0]
        return (f"{'En posición: ' + ', '.join(held) + ' · ' if held else ''}Acierto fuera de muestra {acc} · "
                f"P máx {st['pmax']:.2f} (umbral {self.p.thr:.2f}) · {st['n_signals']} señales")


# ======================================================================================
# #10 Arbitraje cross-exchange vía riel XRP (Bitso <-> Binance / KuCoin)
# ======================================================================================
class XrpRailBot(Bot):
    """Mide si el spread entre Bitso y Binance/KuCoin supera de verdad los costos, y simula la captura.

    Es una COTA SUPERIOR optimista: asume fondos pre-posicionados en cada exchange (sin transferir en la ruta
    crítica), ejecución instantánea al mejor precio y el tamaño disponible en la punta del libro. Solo ve una
    foto del mercado por corrida (no un flujo continuo): estima CUÁNTAS VECES aparece una oportunidad, no
    reproduce la carrera de latencia con bots profesionales. Si ni así hay oportunidades netas, la idea no se
    sostiene con estas comisiones."""
    kind = "xrp_rail"
    strategy_label = "Arbitraje XRP · Bitso ↔ Binance/KuCoin con fondos pre-posicionados (cota superior)"
    DEFAULTS = dict(threshold=0.003, trade_frac=0.30, slip_bps=5.0, max_imbalance=0.35, rebalance_cost=0.0005,
                    fees={"bitso": 0.0036, "binance": 0.0010, "kucoin": 0.0010})
    COLS = ("bid", "ask", "bq", "aq")

    def init_state(self) -> dict:
        return {"samples": 0, "opps": 0, "best_net": None, "sum_net": 0.0, "best_gross": None,
                "mxn_gap_max": 0.0, "inv": {}, "rebalances": 0, "note": "Sin muestras aún"}

    def _quotes(self, ctx: Ctx) -> dict:
        out = {}
        for v in self.p.fees:
            vals = [ctx.v(self.symbols[0], f"{v}_{c}") for c in self.COLS]
            if _ok(*vals[:2]) and vals[0] > 0 and vals[1] > 0:
                out[v] = vals
        return out

    def on_bar(self, ctx: Ctx) -> None:
        p, st, w = self.p, self.st, ctx.wallet
        q = self._quotes(ctx)
        if "bitso" not in q or len(q) < 2:
            return                                               # barra sin foto del mercado (o Bitso no respondió)
        gap = ctx.v(self.symbols[0], "bitso_mxn_gap")
        if _ok(gap):
            st["mxn_gap_max"] = max(st["mxn_gap_max"], abs(gap))
        slip = p.slip_bps / 1e4
        best = None
        for a in q:                                              # compra en `a` (ask), vende en `b` (bid)
            for b in q:
                if a == b or "bitso" not in (a, b):
                    continue
                gross = q[b][0] / q[a][1] - 1.0
                net = gross - p.fees[a] - p.fees[b] - 2 * slip
                if best is None or net > best[0]:
                    best = (net, gross, a, b)
        net, gross, a, b = best
        st["samples"] += 1
        st["sum_net"] += net
        st["best_net"] = net if st["best_net"] is None else max(st["best_net"], net)
        st["best_gross"] = gross if st["best_gross"] is None else max(st["best_gross"], gross)
        st["note"] = f"Mejor ruta ahora: {a}→{b}, bruto {gross:+.2%}, neto {net:+.2%}"
        if net < p.threshold:
            return
        depth = [x for x in (q[a][3] * q[a][1], q[b][2] * q[b][0]) if math.isfinite(x) and x > 0]
        size = min([p.trade_frac * w.initial_cash] + depth)
        if size < w.profile.min_notional * 2:
            return
        inv = st["inv"]
        inv[a] = inv.get(a, 0.0) + size                          # en `a` se acumuló XRP; en `b` se agotó
        inv[b] = inv.get(b, 0.0) - size
        pnl = size * net
        fee = size * (p.fees[a] + p.fees[b])
        w.book(ctx.ts, "XRPUSDT", "sell", "arb", size / q[a][1], q[b][0], fee=fee, realized=pnl,
               reason=f"{a}->{b}")
        st["opps"] += 1
        w._event("info", f"Oportunidad {a}→{b}: bruto {gross:+.2%}, neto {net:+.2%} sobre {size:,.0f} USDT")
        if max(abs(v) for v in inv.values()) > p.max_imbalance * w.initial_cash:   # rebalanceo por el riel XRP
            moved = sum(abs(v) for v in inv.values()) / 2
            cost = moved * p.rebalance_cost
            w.book(ctx.ts, "XRPUSDT", "buy", "arb", moved / q[a][1], q[a][1], fee=cost, realized=-cost,
                   reason="rebalance_xrp_rail")
            st["inv"], st["rebalances"] = {}, st["rebalances"] + 1

    def status_detail(self, wallet: PaperWallet) -> str:
        st = self.st
        if not st["samples"]:
            return st["note"]
        mean = st["sum_net"] / st["samples"]
        return (f"{st['samples']} muestras · neto medio {mean:+.2%} · mejor {st['best_net']:+.2%} · "
                f"{st['opps']} oportunidades ≥ {self.p.threshold:.2%}")


BOT_CLASSES = {"carry": CarryBot, "stable": StableBot, "dca": DcaBot, "grid": GridBot,
               "meanrev": MeanReversionBot, "mm": MarketMakerBot, "trend": TrendBot,
               "breakout": BreakoutBot, "ml": MLBot, "xrp_rail": XrpRailBot}


def build_bot(spec: dict, bar_ms: int) -> Bot:
    try:
        return BOT_CLASSES[spec["kind"]](spec, bar_ms)
    except KeyError as e:
        raise KeyError(f"Tipo de bot desconocido: {spec.get('kind')}") from e
