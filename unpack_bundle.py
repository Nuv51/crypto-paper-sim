#!/usr/bin/env python
"""python unpack_bundle.py code/bundle.json DESTINO  -> recrea el proyecto en DESTINO."""
import json, sys
from pathlib import Path

src, dst = Path(sys.argv[1]), Path(sys.argv[2])
for rel, text in json.loads(src.read_text(encoding="utf-8")).items():
    p = dst / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
print(f"desempaquetado en {dst}")
