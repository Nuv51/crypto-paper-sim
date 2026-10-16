"""Wallet virtual con ejecución realista: comisiones, slippage y órdenes límite.

Reglas de ejecución (todas conservadoras, para no inflar resultados):
  * Una orden enviada al cierre de la barra t NUNCA se llena en esa misma barra: se evalúa desde t+1.
  * Órdenes de mercado: se llenan a la APERTURA de t+1, con slippage adverso y comisión taker.
  * Órdenes límite de compra: se llenan solo si el mínimo de la barra queda ESTRICTAMENTE por debajo
    del precio (no basta con "tocar" el nivel). Venta: el máximo debe quedar estrictamente por encima.
    Se llenan al precio límite, con comisión maker.
  * Spot long-only: no hay posiciones cortas ni apalancamiento.
  * Las órdenes límite reservan efectivo/cantidad: no se puede gastar dos veces el mismo dinero.

Contabilidad: el costo promedio de cada posición INCLUYE la comisión de compra, y el P&L realizado
de una venta descuenta la comisión de venta. Por eso siempre se cumple:
    equity = efectivo_inicial + P&L_realizado + P&L_no_realizado

Patas fuera de la cartera spot (perpetuo corto del bot de carry, capturas del bot de arbitraje, funding):
las registra el propio bot con `book()` (movimiento de efectivo = P&L realizado, la identidad se conserva) y su
valor no realizado entra en `extra_value`. Aparecen en el historial como operaciones de tipo perp/funding/arb.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Optional

from .exchanges import ExchangeProfile

QTY_DECIMALS = 8
DUST = 1e-10


def floor_qty(x: float, decimals: int = QTY_DECIMALS) -> float:
    """Redondea hacia abajo (como los filtros de lote/step size de los exchanges)."""
    f = 10 ** decimals
    return math.floor(x * f) / f


@dataclass
class Order:
    id: int
    symbol: str
    side: str            # 'buy' | 'sell'
    kind: str            # 'market' | 'limit'
    qty: float           # cantidad en moneda base
    price: Optional[float]
    created_ts: int      # ms de la barra en que se envió
    reason: str = ""
    tag: str = ""        # campo libre para la estrategia (p.ej. nivel del grid)


@dataclass
class Fill:
    ts: int
    bot_id: str
    exchange: str
    order_id: int
    symbol: str
    side: str
    kind: str
    qty: float
    price: float
    notional: float
    fee: float
    realized_pnl: float  # solo != 0 en ventas
    reason: str
    tag: str


@dataclass
class Position:
    qty: float = 0.0
    avg_cost: float = 0.0   # costo por unidad incluyendo comisiones de compra


class PaperWallet:
    def __init__(self, bot_id: str, profile: ExchangeProfile, cash: float,
                 slippage_bps: float = 3.0):
        self.bot_id = bot_id
        self.profile = profile
        self.cash = float(cash)
        self.initial_cash = float(cash)
        self.slippage = slippage_bps / 1e4
        self.positions: dict[str, Position] = {}
        self.orders: list[Order] = []
        self.realized_pnl = 0.0
        self.fees_paid = 0.0
        self._next_id = 1
        self._events: list[tuple[str, str]] = []
        self.extra_value = 0.0                 # P&L no realizado de patas fuera de la cartera spot (p.ej. perpetuo)
        self._extra_fills: list["Fill"] = []

    # ------------------------------------------------------------------ consultas
    def pos(self, symbol: str) -> Position:
        return self.positions.setdefault(symbol, Position())

    def open_orders(self, symbol: Optional[str] = None, side: Optional[str] = None,
                    kind: Optional[str] = None) -> list[Order]:
        return [o for o in self.orders
                if (symbol is None or o.symbol == symbol)
                and (side is None or o.side == side)
                and (kind is None or o.kind == kind)]

    def reserved_cash(self) -> float:
        return sum(o.qty * o.price * (1 + self.profile.maker)
                   for o in self.orders if o.kind == "limit" and o.side == "buy")

    def reserved_qty(self, symbol: str) -> float:
        return sum(o.qty for o in self.orders
                   if o.kind == "limit" and o.side == "sell" and o.symbol == symbol)

    def free_cash(self) -> float:
        return self.cash - self.reserved_cash()

    def free_qty(self, symbol: str) -> float:
        return self.pos(symbol).qty - self.reserved_qty(symbol)

    def equity(self, marks: dict[str, float]) -> float:
        return self.cash + self.extra_value + sum(p.qty * marks[s] for s, p in self.positions.items() if p.qty > 0)

    def unrealized(self, marks: dict[str, float]) -> float:
        return self.extra_value + sum(p.qty * (marks[s] - p.avg_cost) for s, p in self.positions.items() if p.qty > 0)

    # ------------------------------------------------------------------ registro de patas sintéticas
    def book(self, ts: int, symbol: str, side: str, kind: str, qty: float, price: float,
             fee: float = 0.0, realized: float = 0.0, reason: str = "", tag: str = "") -> "Fill":
        """Registra un movimiento fuera de la cartera spot. `realized` ya incluye la comisión (la resta);
        el efectivo se mueve exactamente por `realized`, así la identidad contable se conserva."""
        self.cash += realized
        self.realized_pnl += realized
        self.fees_paid += fee
        f = Fill(ts=ts, bot_id=self.bot_id, exchange=self.profile.key, order_id=0, symbol=symbol, side=side,
                 kind=kind, qty=qty, price=price, notional=qty * price, fee=fee, realized_pnl=realized,
                 reason=reason, tag=tag)
        self._extra_fills.append(f)
        return f

    def drain_extra_fills(self) -> list["Fill"]:
        out, self._extra_fills = self._extra_fills, []
        return out

    # ------------------------------------------------------------------ eventos
    def _event(self, level: str, msg: str) -> None:
        self._events.append((level, msg))

    def drain_events(self) -> list[tuple[str, str]]:
        ev, self._events = self._events, []
        return ev

    # ------------------------------------------------------------------ órdenes
    def submit(self, ts: int, symbol: str, side: str, kind: str, qty: float,
               price: Optional[float] = None, reason: str = "", tag: str = "") -> Optional[Order]:
        if side not in ("buy", "sell") or kind not in ("market", "limit"):
            raise ValueError(f"orden inválida: {side}/{kind}")
        if not (qty > 0) or not math.isfinite(qty):
            self._event("warn", f"{symbol} {side} {kind} rechazada: cantidad inválida ({qty})")
            return None
        if kind == "limit":
            if price is None or not (price > 0):
                self._event("warn", f"{symbol} {side} limit rechazada: precio inválido ({price})")
                return None
            if qty * price < self.profile.min_notional:
                self._event("warn", f"{symbol} {side} limit rechazada: notional {qty*price:.2f} "
                                    f"< mínimo {self.profile.min_notional}")
                return None
            if side == "buy" and qty * price * (1 + self.profile.maker) > self.free_cash() + 1e-9:
                self._event("warn", f"{symbol} buy limit rechazada: efectivo libre insuficiente")
                return None
            if side == "sell" and qty > self.free_qty(symbol) + 1e-12:
                self._event("warn", f"{symbol} sell limit rechazada: cantidad libre insuficiente")
                return None
        od = Order(self._next_id, symbol, side, kind, float(qty),
                   None if price is None else float(price), int(ts), reason, tag)
        self._next_id += 1
        self.orders.append(od)
        return od

    def cancel(self, order_id: int) -> bool:
        n = len(self.orders)
        self.orders = [o for o in self.orders if o.id != order_id]
        return len(self.orders) < n

    def cancel_all(self, symbol: Optional[str] = None, side: Optional[str] = None,
                   kind: Optional[str] = None) -> int:
        keep, n = [], 0
        for o in self.orders:
            match = ((symbol is None or o.symbol == symbol)
                     and (side is None or o.side == side)
                     and (kind is None or o.kind == kind))
            if match:
                n += 1
            else:
                keep.append(o)
        self.orders = keep
        return n

    # ------------------------------------------------------------------ ejecución
    def process_bar(self, ts: int, symbol: str, o: float, h: float, l: float, c: float) -> list[Fill]:
        """Evalúa las órdenes pendientes de `symbol` contra la barra que abre en `ts`."""
        fills: list[Fill] = []

        # 1) mercado: a la apertura
        for od in [x for x in self.orders
                   if x.symbol == symbol and x.kind == "market" and x.created_ts < ts]:
            self.orders.remove(od)
            f = self._fill_market(ts, od, o)
            if f:
                fills.append(f)

        # 2) límite: el más cercano a la apertura primero (orden intrabarra desconocido)
        elig = sorted((x for x in self.orders
                       if x.symbol == symbol and x.kind == "limit" and x.created_ts < ts),
                      key=lambda x: abs(x.price - o))
        for od in elig:
            if od not in self.orders:
                continue
            hit = (od.side == "buy" and l < od.price) or (od.side == "sell" and h > od.price)
            if not hit:
                continue
            self.orders.remove(od)
            if od.side == "sell" and self.pos(symbol).qty + 1e-12 < od.qty:
                self._event("warn", f"{symbol} sell limit descartada: posición insuficiente al llenarse")
                continue
            fills.append(self._execute(ts, od, od.qty, od.price, self.profile.maker))
        return fills

    def _fill_market(self, ts: int, od: Order, open_px: float) -> Optional[Fill]:
        taker = self.profile.taker
        if od.side == "buy":
            px = open_px * (1 + self.slippage)
            max_qty = floor_qty(self.free_cash() / (px * (1 + taker)))
            qty = min(od.qty, max_qty)
            if qty < od.qty * 0.999:
                self._event("info", f"{od.symbol} compra a mercado recortada por efectivo: "
                                    f"{od.qty:.6f} -> {qty:.6f}")
            if qty <= 0 or qty * px < self.profile.min_notional:
                self._event("warn", f"{od.symbol} compra a mercado rechazada (sin efectivo / bajo mínimo)")
                return None
        else:
            px = open_px * (1 - self.slippage)
            held = self.pos(od.symbol).qty
            qty = min(od.qty, held)
            closing_all = qty >= held - 1e-12
            if qty <= 0:
                self._event("warn", f"{od.symbol} venta a mercado descartada: sin posición")
                return None
            if qty * px < self.profile.min_notional and not closing_all:
                self._event("warn", f"{od.symbol} venta a mercado rechazada: bajo mínimo")
                return None
        return self._execute(ts, od, qty, px, taker)

    def _execute(self, ts: int, od: Order, qty: float, px: float, fee_rate: float) -> Fill:
        notional = qty * px
        fee = notional * fee_rate
        pos = self.pos(od.symbol)
        if od.side == "buy":
            cost = notional + fee
            new_qty = pos.qty + qty
            pos.avg_cost = (pos.qty * pos.avg_cost + cost) / new_qty
            pos.qty = new_qty
            self.cash -= cost
            pnl = 0.0
        else:
            pnl = qty * (px - pos.avg_cost) - fee
            pos.qty -= qty
            if pos.qty < DUST:
                pos.qty, pos.avg_cost = 0.0, 0.0
            self.cash += notional - fee
            self.realized_pnl += pnl
        self.fees_paid += fee
        return Fill(ts=ts, bot_id=self.bot_id, exchange=self.profile.key, order_id=od.id,
                    symbol=od.symbol, side=od.side, kind=od.kind, qty=qty, price=px,
                    notional=notional, fee=fee, realized_pnl=pnl, reason=od.reason, tag=od.tag)

    # ------------------------------------------------------------------ persistencia
    def to_dict(self) -> dict:
        return {
            "cash": self.cash, "initial_cash": self.initial_cash,
            "realized_pnl": self.realized_pnl, "fees_paid": self.fees_paid,
            "next_id": self._next_id, "extra_value": self.extra_value,
            "positions": {s: [p.qty, p.avg_cost] for s, p in self.positions.items()},
            "orders": [asdict(o) for o in self.orders],
        }

    def load_dict(self, d: dict) -> None:
        self.cash = d["cash"]
        self.initial_cash = d["initial_cash"]
        self.realized_pnl = d["realized_pnl"]
        self.fees_paid = d["fees_paid"]
        self._next_id = d["next_id"]
        self.extra_value = d.get("extra_value", 0.0)
        self.positions = {s: Position(q, a) for s, (q, a) in d["positions"].items()}
        self.orders = [Order(**o) for o in d["orders"]]
