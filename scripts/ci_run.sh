#!/usr/bin/env bash
# Un paso del simulador en CI (GitHub Actions) — también se puede probar en local.
#   SOURCE=binance|synthetic  STORE=store  SUMMARY_FILE=ruta  NOTIFY_FILE=ruta  TABLE_FILE=ruta  FRESH=true  bash scripts/ci_run.sh
# Guarda en STORE/<SOURCE>/{state/ledger.json, data/*.json, index.html}. Si falla, NO toca el estado anterior.
# FRESH=true: reinicia la simulación (el estado anterior se conserva como state/ledger.prev.json).
# NOTIFY_FILE recibe el texto de operaciones/alertas nuevas (vacío si no hubo). TABLE_FILE, la tabla markdown por bot.
# Salida: 0 ok · 1 error · 2 sin datos/red (igual que cloud_step.py).
set -u
SOURCE="${SOURCE:-binance}"
STORE="${STORE:-store}"
SUMMARY_FILE="${SUMMARY_FILE:-/dev/null}"
NOTIFY_FILE="${NOTIFY_FILE:-/dev/null}"
TABLE_FILE="${TABLE_FILE:-/dev/null}"
FRESH="${FRESH:-false}"
DEST="$STORE/$SOURCE"
OUT="$(mktemp -d)"
mkdir -p "$DEST/state" "$DEST/data"
: > "$NOTIFY_FILE"; : > "$TABLE_FILE"

if [ "$FRESH" = "true" ] && [ -f "$DEST/state/ledger.json" ]; then
  mv "$DEST/state/ledger.json" "$DEST/state/ledger.prev.json"
  rm -f "$DEST/data/dashboard.json"                      # sin comparar con la simulación anterior
  echo "FRESH: el estado anterior quedó en state/ledger.prev.json"
fi

STATE_ARGS=()
if [ -f "$DEST/state/ledger.json" ]; then STATE_ARGS=(--state "$DEST/state/ledger.json"); fi
[ -f "$DEST/data/dashboard.json" ] && cp "$DEST/data/dashboard.json" "$OUT/prev_dashboard.json"

python cloud_step.py "${STATE_ARGS[@]}" --out "$OUT" --source "$SOURCE"
CODE=$?

[ -f "$OUT/status.json" ] && cp "$OUT/status.json" "$DEST/data/status.json"
if [ "$CODE" -eq 0 ]; then
  cp "$OUT/ledger.json" "$DEST/state/ledger.json"
  cp "$OUT/dashboard.json" "$DEST/data/dashboard.json"
  cp web/index.html "$DEST/index.html"
  python scripts/digest.py trades --old "$OUT/prev_dashboard.json" --new "$OUT/dashboard.json" > "$NOTIFY_FILE" 2>/dev/null || : > "$NOTIFY_FILE"
  python scripts/digest.py table --dashboard "$OUT/dashboard.json" > "$TABLE_FILE" 2>/dev/null || : > "$TABLE_FILE"
fi

CODE="$CODE" OUT="$OUT" python - > "$SUMMARY_FILE" <<'PY'
import json, os
code = int(os.environ["CODE"]); out = os.environ["OUT"]
st = json.load(open(f"{out}/status.json")) if os.path.exists(f"{out}/status.json") else {}
if code != 0:
    print(f"FALLÓ (código {code}): {st.get('message', 'sin detalle')[:300]}")
else:
    k = json.load(open(f"{out}/dashboard.json"))["kpis"]
    f = lambda v, d=0: "—" if v is None else f"{v:,.{d}f}"
    s = lambda v, d=0: "—" if v is None else f"{v:+,.{d}f}"
    print(f"OK · {st.get('bars_processed', 0)} barras · Equity {f(k['equity'])} · P&L {s(k['pnl'])} · "
          f"ROI {s(k['roi'], 2)}% · Peor DD {f(k['max_dd'], 2)}% · {k['n_trades']} ops")
PY
cat "$SUMMARY_FILE" 2>/dev/null || true
exit "$CODE"
