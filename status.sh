#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 http://127.0.0.1:5000/ || true)
if [[ "$HTTP_CODE" =~ ^[234][0-9]{2}$ ]]; then
  OPENALGO_STATUS="UP(${HTTP_CODE})"
else
  OPENALGO_STATUS="DOWN"
fi

if command -v tmux >/dev/null 2>&1; then
  TMUX_WINS=$(tmux list-windows -a -F "#{session_name}:#{window_index}:#{window_name}" 2>/dev/null | paste -sd "," - || true)
  TMUX_STATUS="${TMUX_WINS:-none}"
else
  TMUX_STATUS="no-tmux"
fi

CSV_SUMMARY=$(python3 - <<'PY'
import csv, datetime, os

today = datetime.date.today().strftime("%Y-%m-%d")

def summarize(path, label):
    if not os.path.isfile(path):
        return f"{label}: missing"
    rows = []
    with open(path, "r", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return f"{label}: 0T ₹0.00 (last: none)"
    today_rows = [r for r in rows if str(r.get("Timestamp", "")).startswith(today)]
    cum_pnl = sum(float(r.get("Net_PnL", 0) or 0) for r in today_rows)
    last = rows[-1]
    last_sym = last.get("Symbol", "?")
    last_net = float(last.get("Net_PnL", 0) or 0)
    last_reason = last.get("Exit_Reason", "?")
    return f"{label}: {len(today_rows)}T ₹{cum_pnl:+.2f} (last: {last_sym} ₹{last_net:+.2f} {last_reason})"

print(f"{summarize('v3_paper_trades_log.csv', 'Options')} | {summarize('equity_paper_trades_log.csv', 'Equity')}")
PY
)

echo "OpenAlgo: ${OPENALGO_STATUS} | tmux: [${TMUX_STATUS}] | ${CSV_SUMMARY}"
