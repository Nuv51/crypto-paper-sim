"""Motor de simulación: el mismo bucle sirve para REPLAY (historial real a toda velocidad) y LIVE
(una barra nueva cada hora, con estado persistido para pausar/reanudar).

Orden dentro de cada barra, para cada bot (sin mirar al futuro):
   1) se ejecutan las órdenes pendientes contra la barra (mercado a la apertura, límite si el precio las cruza);
      luego `bot.mark` registra las patas fuera de spot (perpetuo, funding, capturas de arbitraje)
   2) se valora el portafolio al cierre y se registra el equity
   3) control de riesgo del bot (drawdown máximo -> liquidar / pausar 7 días y reanudar solo / retirar tras 3 rupturas)
   4) la estrategia decide con la información hasta el cierre de esta barra
   5) freno global: si el portafolio entero cae demasiado desde su máximo, se liquida todo y se pausa
Todo es automático: ninguna regla de riesgo espera una acción manual.
"""
from __future__ import annotations

import json
import math
import time
from typing import Callable, Optional

import pandas as pd

from .bots import Bot, Ctx, build_bot
from .broker import PaperWallet
from .data import INTERVAL_MS
from .exchanges import get_exchange
from .ledger import Ledger


DEFAULT_PORTFOLIO_RISK = {"max_drawdown": 0.10, "cooldown_bars": 168, "warn_at": 0.8}


class BotRuntime:
    def __init__(self, bot: Bot, wallet: PaperWallet):
        self.bot, self.wallet = bot, wallet
        self.peak = wallet.initial_cash
        self.status = "active"       # active | paused | retired (halted solo si la acción es liquidate_and_halt)
        self.reason = ""
        self.pause_until = 0
        self.flagged = False
        self.strikes: list[int] = []   # marcas de tiempo de las rupturas recientes del límite de drawdown
        self.warned = False            # ya se avisó que el bot va cerca de su límite
        self.expo: dict = {}           # cantidad expuesta al precio al cierre de la barra anterior (para la atribución)
        self.last_marks: dict = {}     # cierres de la barra anterior


def align(frames: dict[str, pd.DataFrame]) -> tuple[list[int], dict[str, pd.DataFrame]]:
    """Recorta todas las monedas a las marcas de tiempo que tienen en común."""
    common = None
    for df in frames.values():
        common = df.index if common is None else common.intersection(df.index)
    common = common.sort_values()
    return [int(t) for t in common], {s: df.loc[common] for s, df in frames.items()}


class Engine:
    def __init__(self, ledger: Ledger, bots_cfg: list[dict], portfolio_capital: float,
                 interval: str = "1h", only: Optional[list[str]] = None,
                 portfolio_risk: Optional[dict] = None):
        self.ledger = ledger
        self.prisk = dict(DEFAULT_PORTFOLIO_RISK, **(portfolio_risk or {}))
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
        self._attrib: list[tuple] = []
        self._last_ts = 0
        # freno global: estado del portafolio completo (se guarda en meta, no en un bot)
        self.g = {"peak": sum(rt.wallet.initial_cash for rt in self.runtimes.values()),
                  "status": "active", "until": 0, "trips": 0}

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
            rt.strikes, rt.warned = list(d.get("strikes", [])), d.get("warned", False)
            rt.expo, rt.last_marks = dict(d.get("expo", {})), dict(d.get("last_marks", {}))
        g = self.ledger.get_meta("portfolio_risk")
        if g:
            self.g.update({k: v for k, v in json.loads(g).items() if k in self.g})

    def save_state(self) -> None:
        for bid, rt in self.runtimes.items():
            self.ledger.save_state(bid, {
                "wallet": rt.wallet.to_dict(), "strategy": rt.bot.get_state(), "peak": rt.peak,
                "status": rt.status, "reason": rt.reason, "pause_until": rt.pause_until,
                "flagged": rt.flagged, "strikes": rt.strikes, "warned": rt.warned,
                "expo": rt.expo, "last_marks": rt.last_marks})
        self.ledger.set_meta("portfolio_risk", json.dumps({**self.g, "limit": self.prisk.get("max_drawdown"),
                                                           "cooldown_bars": self.prisk.get("cooldown_bars")}))
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
        if self._attrib:
            L.add_attrib(self._attrib)
        self._trades, self._equity, self._events, self._bars, self._attrib = [], [], [], [], []
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
        ctxs: dict[str, Ctx] = {}
        eqs: dict[str, float] = {}
        for bid, rt in self.runtimes.items():
            bot, w = rt.bot, rt.wallet
            ctx = ctxs[bid] = Ctx(ts, i, w, arrays[bid], self.bar_ms)

            for sym in bot.symbols:                                   # 1) ejecución
                o, h, l, c = rows[sym]
                for f in w.process_bar(ts, sym, o, h, l, c):
                    self._trades.append((f.ts, f.bot_id, f.exchange, f.symbol, f.side, f.kind, f.qty,
                                         f.price, f.notional, f.fee, f.realized_pnl, f.reason, f.tag))
                    bot.on_fill(f, ctx)

            bot.mark(ctx, rows)                                       # 1b) patas fuera de spot (perp, funding, arb)
            self._drain_extra(w)

            marks = {s: rows[s][3] for s in bot.symbols}              # 2) valoración
            eq = eqs[bid] = w.equity(marks)
            rt.peak = max(rt.peak, eq)
            self._equity.append((ts, bid, eq, w.cash, w.realized_pnl, w.unrealized(marks), w.fees_paid))
            self._attribute(rt, ts, marks)

            self._risk_check(rt, ctx, eq)                             # 3) riesgo del bot

            if rt.status == "active" and i >= bot.warmup:             # 4) estrategia
                bot.on_bar(ctx)
                self._drain_extra(w)

        self._portfolio_check(ts, ctxs, eqs)                          # 5) freno global

        for bid, rt in self.runtimes.items():
            for lvl, msg in rt.wallet.drain_events():
                self._events.append((ts, bid, lvl, msg))

    def _attribute(self, rt: BotRuntime, ts: int, marks: dict) -> None:
        """Parte del cambio de equity de esta barra que pone el mercado: lo que ya tenía el bot al cierre anterior
        (cantidad neta, con los cortos restando) por lo que se movió cada precio. El resto del cambio (operar,
        comisiones, slippage, funding, capturas de arbitraje) se atribuye al bot en la exportación."""
        mk = sum(q * (marks[s] - rt.last_marks[s]) for s, q in rt.expo.items() if s in marks and s in rt.last_marks)
        self._attrib.append((ts, rt.bot.id, mk))
        rt.expo = rt.bot.exposure(rt.wallet)
        rt.last_marks = {s: float(v) for s, v in marks.items()}

    def _drain_extra(self, w: PaperWallet) -> None:
        for f in w.drain_extra_fills():
            self._trades.append((f.ts, f.bot_id, f.exchange, f.symbol, f.side, f.kind, f.qty,
                                 f.price, f.notional, f.fee, f.realized_pnl, f.reason, f.tag))

    def _risk_check(self, rt: BotRuntime, ctx: Ctx, eq: float) -> None:
        """Control de riesgo de un bot. Sin pasos manuales: pausa y reanuda sola; si rompe el límite varias veces
        seguidas en poco tiempo, el bot se retira (queda registrado como resultado, no como pendiente)."""
        rk, bot, ts = rt.bot.risk, rt.bot, ctx.ts
        if rt.status == "paused" and ts >= rt.pause_until:
            rt.status, rt.reason, rt.peak, rt.warned = "active", "", eq, False
            bot.reset()
            self._events.append((ts, bot.id, "info", "Reanuda sola tras la pausa (peak de equity reiniciado)"))
        limit = rk.get("max_drawdown")
        if not limit or rt.status != "active":
            return
        dd = 1 - eq / rt.peak if rt.peak > 0 else 0.0
        action = rk.get("action", "liquidate_and_halt")
        if dd >= limit:
            msg = f"Drawdown {dd:.1%} >= límite {limit:.0%}"
            if action == "flag_only":                       # solo informativa: este bot no tiene stop por diseño
                if not rt.flagged:
                    rt.flagged = True
                    rt.reason = "ALERTA (informativa, el bot sigue): " + msg
                    self._events.append((ts, bot.id, "alert", rt.reason))
                return
            bot.on_halt(ctx)
            window = int(rk.get("strike_window_bars", 720)) * self.bar_ms
            rt.strikes = [t for t in rt.strikes if ts - t < window] + [ts]
            max_strikes = int(rk.get("max_strikes", 0) or 0)
            rt.warned = False
            if action == "pause_and_resume" and max_strikes and len(rt.strikes) >= max_strikes:
                rt.status = "retired"
                rt.reason = f"{msg}: {len(rt.strikes)} rupturas en {window // 86_400_000} días, bot retirado"
            elif action == "pause_and_resume":
                days = int(rk.get("cooldown_bars", 168)) * self.bar_ms // 86_400_000
                rt.status = "paused"
                rt.pause_until = ts + int(rk.get("cooldown_bars", 168)) * self.bar_ms
                rt.reason = f"{msg}: liquidado, pausa de {days} días y reanuda solo"
            else:
                rt.status = "halted"
                rt.reason = f"{msg}: liquidado y detenido"
            self._events.append((ts, bot.id, "alert", rt.reason))
            return
        warn_at = float(rk.get("warn_at", 0.8))
        if dd >= limit * warn_at and not rt.warned and action != "flag_only":
            rt.warned = True
            self._events.append((ts, bot.id, "warn",
                                 f"Cerca de su límite: drawdown {dd:.1%} = {dd / limit:.0%} del límite de {limit:.0%}"))
        elif rt.warned and dd < limit * 0.6:
            rt.warned = False
        if rt.flagged and dd < limit * 0.9:
            rt.flagged, rt.reason = False, ""

    def _portfolio_check(self, ts: int, ctxs: dict, eqs: dict) -> None:
        """Freno global: si el portafolio entero cae `max_drawdown` desde su máximo, liquida todos los bots y pausa
        el tiempo configurado; luego todos reanudan solos con el máximo reiniciado."""
        g, pr = self.g, self.prisk
        tot = sum(eqs.values())
        if g["status"] == "paused":
            if ts < g["until"]:
                return
            g.update(status="active", peak=tot)
            self._events.append((ts, "", "info", "Freno global: el portafolio reanuda solo (peak reiniciado)"))
        g["peak"] = max(g["peak"], tot)
        limit = pr.get("max_drawdown")
        if not limit:
            return
        dd = 1 - tot / g["peak"] if g["peak"] > 0 else 0.0
        if dd < limit:
            return
        until = ts + int(pr.get("cooldown_bars", 168)) * self.bar_ms
        for bid, rt in self.runtimes.items():
            if rt.status == "retired":
                continue
            if rt.status == "active":
                rt.bot.on_halt(ctxs[bid])
            rt.pause_until = max(rt.pause_until, until) if rt.status == "paused" else until
            rt.status = "paused"
            rt.flagged, rt.warned = False, False
            rt.reason = f"Freno global del portafolio ({dd:.1%} desde su máximo): liquidado y pausado, reanuda solo"
        g.update(status="paused", until=until, trips=g["trips"] + 1)
        self._events.append((ts, "", "alert",
                             f"FRENO GLOBAL: portafolio {dd:.1%} bajo su máximo (límite {limit:.0%}); "
                             f"todo liquidado, pausa de {int(pr.get('cooldown_bars', 168)) * self.bar_ms // 86_400_000} días y reanuda solo"))

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
