"""Registro de simuladores publicados: escribe <store>/sims.json con cada carpeta que tenga data/dashboard.json.

  python scripts/make_registry.py store

Las páginas de cada tablero leen ../sims.json para comparar TODOS los simuladores; así, al agregar uno nuevo (una carpeta nueva con
su tablero) aparece solo en la pestaña Comparar de todos, sin editar ninguna página. Se omiten las carpetas de prueba con datos
inventados (synthetic*, *-synthetic). Orden estable: primero los históricos (binance, activo, indice, ajustado), luego los demás por nombre;
el orden fija el color de cada simulador en las gráficas, así que no cambia entre tableros.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PRIORITY = ["binance", "activo", "indice", "ajustado"]


def build(store: str | Path) -> list[dict]:
    root = Path(store)
    found = []
    for d in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        name = d.name
        if name.startswith("synthetic") or name.endswith("-synthetic"):
            continue
        f = d / "data" / "dashboard.json"
        if not f.exists():
            continue
        try:
            sim = (json.loads(f.read_text(encoding="utf-8")).get("sim")) or {}
        except Exception:
            continue                                   # tablero ilegible: no se ofrece
        found.append({"dir": name, "id": sim.get("id", name), "name": sim.get("name", name), "desc": sim.get("desc", "")})
    rank = lambda e: (PRIORITY.index(e["dir"]) if e["dir"] in PRIORITY else len(PRIORITY), e["dir"])
    return sorted(found, key=rank)


def main() -> int:
    store = sys.argv[1] if len(sys.argv) > 1 else "store"
    reg = build(store)
    Path(store, "sims.json").write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"sims.json: {', '.join(e['dir'] for e in reg) or 'vacío'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
