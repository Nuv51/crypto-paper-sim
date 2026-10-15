#!/usr/bin/env python
"""Empaqueta el código necesario para la nube en un solo JSON (code/bundle.json).
Una sesión programada nueva no tiene el código: lo descarga del artefacto y lo desempaqueta con unpack_bundle.py.
  python make_bundle.py OUT.json
"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).parent
FILES = ["cloud_step.py", "config.py", "unpack_bundle.py", "web/index.html"] + sorted(f"sim/{p.name}" for p in (ROOT / "sim").glob("*.py"))

def main(out: str) -> None:
    bundle = {f: (ROOT / f).read_text(encoding="utf-8") for f in FILES}
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(bundle)} archivos -> {out} ({Path(out).stat().st_size} bytes)")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "code/bundle.json")
