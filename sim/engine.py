"""Motor de simulación: el mismo bucle sirve para REPLAY (historial real a toda velocidad) y LIVE
(una barra nueva cada hora, con estado persistido para pausar/reanudar).

Orden dentro de cada barra, para cada bot (sin mirar al futuro):
   1) se ejecutan las órdenes pendientes contra la barra (mercado a la apertura, límite si el precio las cruza);
      luego `bot.mark` registra las patas fuera de spot (perpetuo, funding, capturas de arbitraje)
   2) se valora el portafolio al cierre y se registra el equity
   3) control de riesgo (drawdown máximo -> liquidar / pausar / avisar)
   4) la estrategia decide con la información hasta el cierre de esta barra
"""
from __future__ import annotations

import math
import time
from typing import Callable, Optional

import pandas as pd

from .bots import Bot, Ctx, build_bot
from .broker import PaperWallet
from .data import INTERVAL_MS
from .exchanges import get_exchange
from .ledger import Ledger


class BotRuntime:
    def __init__(self, bot: Bot, wallet: PaperWallet):
        self.bot, self.wallet = bot, wallet
        self.peak = wallet.initial_cash
        self.status = "active"       # active | paused | halted
        self.reason = ""
        self.pause_until = 0
        self.flagged = False


def align(frames: dict[str, pd.DataFrame]) -> tuple[list[int], dict[str, pd.DataFrame]]:
    """Recorta todas las monedas a las marcas de tiempo que tienen en común."""
    common = None
    for df in frames.values():
        common = df.index if common is None else common.intersection(df.index)
    common = common.sort_values()
    return [int(t) for t in common], {s: df.loc[common] for s, df in frames.items()}


class Engine:
    def __init__(self, ledger: Ledger, bots_cfg: list[dict], portfolio_capital: float,
                 interval: str = "1h", only: Optional[list[str]] = None):
        self.ledger = ledger
        self.interval = interval
        self.bar_ms = INTERVAL_MS[interval]
        self.portfolio_capital = portfolio_capital
        self.runtimes: dict[str, BotRuntime] = {}
        for cfg in bots_cfg:
            if only and cfg["id"] not in only and cfg["kind"] not in only:
                continue
            spec = dict(cfg, capital=portfolio_capital * cfg["capital_pct"])
            bot = build_bot(spec, self.bar_ms)
            wallet = PaperWallet(bot.id, get_exchange(bot.exchange), bot.capital, bot.slippage_bps)
            self.runtimes[bot.id] = BotRuntime(bot, wallet)
        if not self.runtimes:
            raise ValueError("Ningún bot seleccionado")
        self.symbols = sorted({s for rt in self.runtimes.values() for s in rt.bot.symbols})
        self.max_warmup = max(rt.bot.warmup for rt in self.runtimes.values())
        self._trades: list[tuple] = []
        self._equity: list[tuple] = []
        self._events: list[tuple] = []
        self._bars: list[tuple] = []
        self._last_ts = 0

    # ------------------------------------------------------------------ persistencia
    def register_bots(self, ts: int = 0) -> None:
        for rt in self.runtimes.values():
            self.ledger.upsert_bot({**rt.bot.meta(), "status": rt.status, "status_reason": rt.reason,
                                    "status_detail": rt.bot.status_detail(rt.wallet), "updated_ts": ts})

    def has_saved_state(self) -> bool:
        return all(self.ledger.load_state(i) for i in self.runtimes)

    def load_state(self) -> None:
        for bid, rt in self.runtimes.items():
            d = self.ledger.load_state(bid)
            rt.wallet.load_dict(d["wallet"])
            rt.bot.set_state(d["strategy"])
            rt.peak, rt.status, rt.reason = d["peak"], d["status"], d["reason"]
            rt.pause_until, rt.flagged = d["pause_until"], d.get("flagged", False)

    def save_state(self) -> None:
        for bid, rt in self.runtimes.items():
            self.ledger.save_state(bid, {
                "wallet": rt.wallet.to_dict(), "strategy": rt.bot.get_state(), "peak": rt.peak,
                "status": rt.status, "reason": rt.reason, "pause_until": rt.pause_until,
                "flagged": rt.flagged})
        self.ledger.commit()

    def flush(self) -> None:
        L = self.ledger
        if self._trades:
            L.add_trades(self._trades)
        if self._equity:
            L.add_equity(self._equity)
        if self._events:
            L.add_events(self._events)
        if self._bars:
            L.upsert_bars(self._bars)
        self._trades, self._equity, self._events, self._bars = [], [], [], []
        for bid, rt in self.runtimes.items():
            L.update_bot_status(bid, rt.status, rt.reason, rt.bot.status_detail(rt.wallet), self._last_ts)
        L.commit()

    # ------------------------------------------------------------------ preparación
    def prepare_arrays(self, frames: dict[str, pd.DataFrame]) -> dict:
        arrays: dict = {}
        for bid, rt in self.runtimes.items():
            arrays[bid] = {}
            for sym in rt.bot.symbols:
                prep = rt.bot.prepare(sym, frames[sym])
                arrays[bid][sym] = {c: prep[c].to_numpy(dtype=float) for c in prep.columns}
        return arrays

    # ------------------------------------------------------------------ una barra
    def step(self, ts: int, i: int, rows: dict[str, tuple], arrays: dict) -> None:
        """rows[sym] = (open, high, low, close) de la barra i."""
        self._last_ts = ts
        for bid, rt in self.runtimes.items():
            bot, w = rt.bot, rt.wallet
            ctx = Ctx(ts, i, w, arrays[bid], self.bar_ms)

            for sym in bot.symbols:                                   # 1) ejecución
                o, h, l, c = rows[sym]
                for f in w.process_bar(ts, sym, o, h, l, c):
                    self._trades.append((f.ts, f.bot_id, f.exchange, f.symbol, f.side, f.kind, f.qty,
                                         f.price, f.notional, f.fee, f.realized_pnl, f.reason, f.tag))
                    bot.on_fill(f, ctx)

            bot.mark(ctx, rows)                                       # 1b) patas fuera de spot (perp, funding, arb)
            self._drain_extra(w)

            marks = {s: rows[s][3] for s in bot.symbols}              # 2) valoración
            eq = w.equity(marks)
            rt.peak = max(rt.peak, eq)
            self._equity.append((ts, bid, eq, w.cash, w.realized_pnl, w.unrealized(marks), w.fees_paid))

            self._risk_check(rt, ctx, eq)                             # 3) riesgo

            if rt.status == "active" and i >= bot.warmup:             # 4) estrategia
                bot.on_bar(ctx)
                self._drain_extra(w)

            for lvl, msg in w.drain_events():
                self._events.append((ts, bid, lvl, msg))

    def _drain_extra(self, w: PaperWallet) -> None:
        for f in w.drain_extra_fills():
            self._trades.append((f.ts, f.bot_id, f.exchange, f.symbol, f.side, f.kind, f.qty,
                                 f.price, f.notional, f.fee, f.realized_pnl, f.reason, f.tag))

    def _risk_check(self, rt: BotRuntime, ctx: Ctx, eq: float) -> None:
        rk, bot, ts = rt.bot.risk, rt.bot, ctx.ts
        if rt.status == "paused" and ts >= rt.pause_until:
            rt.status, rt.reason, rt.peak = "active", "", eq
            bot.reset()
            self._events.append((ts, bot.id, "info", "Reanuda tras la pausa obligatoria (peak de equity reiniciado)"))
        limit = rk.get("max_drawdown")
        if not limit or rt.status != "active":
            return
        dd = 1 - eq / rt.peak if rt.peak > 0 else 0.0
        action = rk.get("action", "liquidate_and_halt")
        if dd >= limit:
            msg = f"Drawdown {dd:.1%} >= límite {limit:.0%}"
            if action == "flag_only":
                if not rt.flagged:
                    rt.flagged = True
                    rt.reason = "REVISIÓN MANUAL: " + msg
                    self._events.append((ts, bot.id, "alert", rt.reason))
                return
            bot.on_halt(ctx)
            if action == "pause_and_resume":
                rt.status = "paused"
                rt.pause_until = ts + int(rk.get("cooldown_bars", 168)) * self.bar_ms
                rt.reason = f"{msg}: pausa obligatoria"
            else:
                rt.status = "halted"
                rt.reason = f"{msg}: liquidado, requiere revisión manual"
            self._events.append((ts, bot.id, "alert", rt.reason))
        elif rt.flagged and dd < limit * 0.9:
            rt.flagged, rt.reason = False, ""

    # ------------------------------------------------------------------ REPLAY
    def replay(self, frames: dict[str, pd.DataFrame], progress: Optional[Callable[[str], None]] = print) -> dict:
        idx, fr = align(frames)
        arrays = self.prepare_arrays(fr)
        start = self.max_warmup + 1
        if start >= len(idx) - 1:
            raise ValueError(f"Historial insuficiente: {len(idx)} barras comunes, se necesitan > {start + 1}")
        cols = {s: [fr[s][c].to_numpy(dtype=float).tolist() for c in ("open", "high", "low", "close", "volume")]
                for s in self.symbols}
        self.register_bots(idx[start])
        self._bars = [(s, idx[i], *(cols[s][k][i] for k in range(5)))
                      for s in self.symbols for i in range(start, len(idx))]
        n = len(idx)
        for i in range(start, n):
            rows = {s: (cols[s][0][i], cols[s][1][i], cols[s][2][i], cols[s][3][i]) for s in self.symbols}
            self.step(idx[i], i, rows, arrays)
            if (i - start) % 750 == 0:
                if progress:
                    progress(f"  replay {i - start + 1}/{n - start} barras")
                self.flush()
        self.flush()
        self.save_state()
        self.ledger.set_meta("first_ts", idx[start])
        self.ledger.set_meta("last_ts", idx[-1])
        return {"bars": n - start, "first_ts": idx[start], "last_ts": idx[-1]}

    # ------------------------------------------------------------------ LIVE
    def process_new(self, frames: dict[str, pd.DataFrame], cmc=None) -> int:
        idx, fr = align(frames)
        if len(idx) < self.max_warmup + 2:
            raise ValueError(f"Muy pocas barras ({len(idx)}) para el calentamiento ({self.max_warmup})")
        last_ts = int(self.ledger.get_meta("last_ts", 0) or 0)
        pos = [i for i, t in enumerate(idx) if t > last_ts] if last_ts else [len(idx) - 1]
        if not pos:
            return 0
        if last_ts and idx[pos[0]] - last_ts > self.bar_ms:
            miss = (idx[pos[0]] - last_ts) // self.bar_ms - 1
            self._events.append((idx[pos[0]], "", "warn", f"Hueco de datos: {miss} barras no procesadas"))
        arrays = self.prepare_arrays(fr)
        cols = {s: [fr[s][c].to_numpy(dtype=float).tolist() for c in ("open", "high", "low", "close", "volume")]
                for s in self.symbols}
        if not last_ts:
            self.register_bots(idx[pos[0]])
        for i in pos:
            rows = {s: (cols[s][0][i], cols[s][1][i], cols[s][2][i], cols[s][3][i]) for s in self.symbols}
            self._bars += [(s, idx[i], *(cols[s][k][i] for k in range(5))) for s in self.symbols]
            self.step(idx[i], i, rows, arrays)
        if cmc is not None:
            self._cmc_check(cmc, fr, idx[pos[-1]])
        self.ledger.set_meta("last_ts", idx[pos[-1]])
        if not self.ledger.get_meta("first_ts"):
            self.ledger.set_meta("first_ts", idx[pos[0]])
        self.flush()
        self.save_state()
        return len(pos)

    def _cmc_check(self, cmc, fr: dict[str, pd.DataFrame], ts: int) -> None:
        bases = sorted({s[:-4] for s in self.symbols if s.endswith("USDT")})
        try:
            quotes = cmc.latest(bases)
        except Exception as e:     # la verificación cruzada nunca debe tumbar la simulación
            self._events.append((ts, "", "info", f"CoinMarketCap no disponible: {e}"))
            return
        for b, px in quotes.items():
            ref = float(fr[b + "USDT"]["close"].iloc[-1])
            if ref and abs(px / ref - 1) > 0.03:
                self._events.append((ts, "", "warn", f"{b}: CMC {px:,.4f} vs Binance {ref:,.4f} (>3% de diferencia)"))

    def live(self, feed, poll_seconds: int = 60, lookback: int = 700, cmc=None,
             max_loops: Optional[int] = None, log: Callable[[str], None] = print) -> None:
        loops = 0
        while True:
            try:
                frames = {s: feed.latest_closed(s, self.interval, lookback) for s in self.symbols}
                n = self.process_new(frames, cmc)
                if n:
                    log(f"[live] {n} barra(s) nueva(s) procesada(s)")
            except KeyboardInterrupt:
                raise
            except Exception as e:      # red caída, rate limit, etc.: se reintenta en el siguiente ciclo
                log(f"[live] error ({type(e).__name__}): {e} — reintento en {poll_seconds}s")
            loops += 1
            if max_loops is not None and loops >= max_loops:
                break
            time.sleep(poll_seconds)
