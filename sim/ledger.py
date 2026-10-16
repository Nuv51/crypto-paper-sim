"""Registro persistente en SQLite: operaciones, curva de equity, barras, eventos y estado de los bots.

Se usa modo WAL para que el dashboard pueda leer mientras el motor escribe.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS bots(
    bot_id TEXT PRIMARY KEY, name TEXT, strategy TEXT, exchange TEXT, symbols TEXT,
    vol_profile TEXT, risk_level TEXT, capital REAL, differentiator TEXT, params TEXT,
    status TEXT, status_reason TEXT, status_detail TEXT, updated_ts INTEGER);
CREATE TABLE IF NOT EXISTS trades(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, bot_id TEXT, exchange TEXT, symbol TEXT,
    side TEXT, kind TEXT, qty REAL, price REAL, notional REAL, fee REAL, realized_pnl REAL,
    reason TEXT, tag TEXT);
CREATE TABLE IF NOT EXISTS equity(
    ts INTEGER, bot_id TEXT, equity REAL, cash REAL, realized_pnl REAL, unrealized_pnl REAL,
    fees_paid REAL, PRIMARY KEY(ts, bot_id));
CREATE TABLE IF NOT EXISTS bars(
    symbol TEXT, ts INTEGER, open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY(symbol, ts));
CREATE TABLE IF NOT EXISTS events(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, bot_id TEXT, level TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS bot_state(bot_id TEXT PRIMARY KEY, state TEXT);
CREATE TABLE IF NOT EXISTS attrib(ts INTEGER, bot_id TEXT, market REAL, PRIMARY KEY(ts, bot_id));
"""


class Ledger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(self.path), timeout=30)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA synchronous=NORMAL")
        self.con.executescript(SCHEMA)
        self.con.commit()

    # ---------------------------------------------------------------- meta
    def set_meta(self, key: str, value) -> None:
        self.con.execute("INSERT INTO meta(key,value) VALUES(?,?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
        self.con.commit()

    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        r = self.con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r[0] if r else default

    # ---------------------------------------------------------------- bots
    def upsert_bot(self, b: dict) -> None:
        self.con.execute(
            "INSERT INTO bots(bot_id,name,strategy,exchange,symbols,vol_profile,risk_level,capital,"
            "differentiator,params,status,status_reason,status_detail,updated_ts) "
            "VALUES(:bot_id,:name,:strategy,:exchange,:symbols,:vol_profile,:risk_level,:capital,"
            ":differentiator,:params,:status,:status_reason,:status_detail,:updated_ts) "
            "ON CONFLICT(bot_id) DO UPDATE SET name=excluded.name, strategy=excluded.strategy, "
            "exchange=excluded.exchange, symbols=excluded.symbols, vol_profile=excluded.vol_profile, "
            "risk_level=excluded.risk_level, capital=excluded.capital, "
            "differentiator=excluded.differentiator, params=excluded.params, "
            "status=excluded.status, status_reason=excluded.status_reason, "
            "status_detail=excluded.status_detail, updated_ts=excluded.updated_ts", b)
        self.con.commit()

    def update_bot_status(self, bot_id: str, status: str, reason: str, detail: str, ts: int) -> None:
        self.con.execute("UPDATE bots SET status=?, status_reason=?, status_detail=?, updated_ts=? "
                         "WHERE bot_id=?", (status, reason, detail, ts, bot_id))

    # ---------------------------------------------------------------- escritura por lotes
    def add_trades(self, rows: Iterable[tuple]) -> None:
        self.con.executemany(
            "INSERT INTO trades(ts,bot_id,exchange,symbol,side,kind,qty,price,notional,fee,"
            "realized_pnl,reason,tag) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)

    def add_equity(self, rows: Iterable[tuple]) -> None:
        self.con.executemany(
            "INSERT OR REPLACE INTO equity(ts,bot_id,equity,cash,realized_pnl,unrealized_pnl,fees_paid) "
            "VALUES(?,?,?,?,?,?,?)", rows)

    def upsert_bars(self, rows: Iterable[tuple]) -> None:
        self.con.executemany(
            "INSERT OR REPLACE INTO bars(symbol,ts,open,high,low,close,volume) VALUES(?,?,?,?,?,?,?)", rows)

    def add_attrib(self, rows: Iterable[tuple]) -> None:
        """(ts, bot_id, market): parte del cambio de equity de la barra que se debe al movimiento de precios."""
        self.con.executemany("INSERT OR REPLACE INTO attrib(ts,bot_id,market) VALUES(?,?,?)", rows)

    def add_events(self, rows: Iterable[tuple]) -> None:
        self.con.executemany("INSERT INTO events(ts,bot_id,level,message) VALUES(?,?,?,?)", rows)

    def save_state(self, bot_id: str, state: dict) -> None:
        self.con.execute("INSERT INTO bot_state(bot_id,state) VALUES(?,?) "
                         "ON CONFLICT(bot_id) DO UPDATE SET state=excluded.state",
                         (bot_id, json.dumps(state)))

    def load_state(self, bot_id: str) -> Optional[dict]:
        r = self.con.execute("SELECT state FROM bot_state WHERE bot_id=?", (bot_id,)).fetchone()
        return json.loads(r[0]) if r else None

    # ---------------------------------------------------------------- snapshot (modo nube)
    TABLES = ("meta", "bots", "trades", "equity", "bars", "events", "bot_state", "attrib")

    def dump(self) -> dict:
        """Serializa toda la base a un dict JSON-able (el modo nube no tiene disco entre corridas)."""
        self.con.commit()
        out = {}
        for t in self.TABLES:
            cur = self.con.execute(f"SELECT * FROM {t}")
            out[t] = {"columns": [d[0] for d in cur.description], "rows": [list(r) for r in cur.fetchall()]}
        return out

    def restore(self, snap: dict) -> None:
        """Reemplaza el contenido de la base con un snapshot creado por dump()."""
        for t in self.TABLES:
            self.con.execute(f"DELETE FROM {t}")
            d = snap.get(t)
            if not d or not d["rows"]:
                continue
            cols = d["columns"]
            self.con.executemany(
                f"INSERT INTO {t}({','.join(cols)}) VALUES({','.join('?' * len(cols))})", d["rows"])
        self.con.commit()

    def prune_bars(self, keep: int = 800) -> None:
        """Conserva solo las últimas `keep` velas por moneda (el historial completo no hace falta para seguir)."""
        for (sym,) in self.con.execute("SELECT DISTINCT symbol FROM bars").fetchall():
            r = self.con.execute("SELECT ts FROM bars WHERE symbol=? ORDER BY ts DESC LIMIT 1 OFFSET ?",
                                 (sym, keep)).fetchone()
            if r:
                self.con.execute("DELETE FROM bars WHERE symbol=? AND ts<=?", (sym, r[0]))
        self.con.commit()

    def commit(self) -> None:
        self.con.commit()

    def close(self) -> None:
        self.con.commit()
        self.con.close()


def read_only_connection(path: str | Path) -> sqlite3.Connection:
    """Conexión de solo lectura para el dashboard."""
    return sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True, timeout=30)


def read_df(con: sqlite3.Connection, sql: str, params: tuple = ()) -> pd.DataFrame:
    return pd.read_sql_query(sql, con, params=params)
