import datetime
import json
import os
import sqlite3
import time
import urllib.request
import config

OPENALGO_DB = "/home/zahsay/trading-projects/openalgo/db/openalgo.db"


def get_nearest_expiry_from_db(index_name, exchange, opt_type):
  if not os.path.isfile(OPENALGO_DB):
    return None, []

  conn = sqlite3.connect(OPENALGO_DB)
  cur = conn.cursor()
  # Inspect symtoken table columns dynamically to stay version-proof
  cur.execute("PRAGMA table_info(symtoken)")
  cols = [row[1] for row in cur.fetchall()]
  if not cols:
    conn.close()
    return None, []

  cur.execute(
      "SELECT symbol, expiry, strike, lotsize FROM symtoken "
      "WHERE exchange = ? AND name = ? AND instrumenttype = ?",
      (exchange, index_name, opt_type),
  )
  rows = cur.fetchall()
  conn.close()

  today = datetime.date.today()
  valid = []
  for sym, exp_str, strike, lotsize in rows:
    try:
      exp_dt = datetime.datetime.strptime(exp_str, "%d-%b-%y").date()
    except Exception:
      continue
    if exp_dt >= today:
      valid.append((exp_dt, sym, float(strike), int(lotsize)))

  if not valid:
    return None, []

  nearest_exp = min(r[0] for r in valid)
  filtered = [r for r in valid if r[0] == nearest_exp]
  filtered.sort(key=lambda x: x[2], reverse=(opt_type == "PE"))
  return nearest_exp.strftime("%d-%b-%Y"), filtered


def fetch_quote_fast(symbol, exchange, timeout=3.0):
  req = urllib.request.Request(
      f"{config.OPENALGO_HOST}/api/v1/quotes",
      data=json.dumps({
          "apikey": config.OPENALGO_API_KEY,
          "symbol": symbol,
          "exchange": exchange,
      }).encode(),
      headers={"Content-Type": "application/json"},
  )
  with urllib.request.urlopen(req, timeout=timeout) as resp:
    payload = json.loads(resp.read().decode())
    if payload.get("status") == "success" and "data" in payload:
      return payload["data"]
  return None


def run_strike_screener():
  print("\n=== INSTANT PRE-MARKET STRIKE SCREENER (SQLite + 3s Timeout) ===")
  idx_in = input("Index [SENSEX / NIFTY] (default SENSEX): ").strip().upper() or "SENSEX"
  dir_in = input("Directional Bias [CE / PE] (default CE): ").strip().upper() or "CE"
  spot_in = input(f"Approx {idx_in} Spot Price (e.g. 84000 or 25000): ").strip()

  if not spot_in:
    print("[ERROR] Spot price is required.")
    return

  spot = float(spot_in)
  exchange = "BFO" if idx_in == "SENSEX" else "NFO"
  if idx_in == "NIFTY":
    min_prem, max_prem = 75.0, 180.0
  else:
    min_prem = getattr(config, "PREMIUM_MIN_THRESHOLD", 150.0)
    max_prem = getattr(config, "PREMIUM_MAX_THRESHOLD", 330.0)

  t0 = time.time()
  exp_str, contracts = get_nearest_expiry_from_db(idx_in, exchange, dir_in)
  if not contracts:
    print("[ERROR] No active contracts in OpenAlgo SQLite DB. Login to OpenAlgo to sync master contracts.")
    return

  # Filter ATM to +1000 pts OTM (max 10 strikes)
  if dir_in == "CE":
    selected = [c for c in contracts if (spot - 100) <= c[2] <= (spot + 1000)][:10]
  else:
    selected = [c for c in contracts if (spot - 1000) <= c[2] <= (spot + 100)][:10]

  lot_size = selected[0][3] if selected else (20 if idx_in == "SENSEX" else 65)
  print(
      f"\n[DB LOOKUP: {time.time()-t0:.3f}s] Expiry: {exp_str} | Lot: {lot_size} |"
      f" Checking {len(selected)} strikes...\n",
      flush=True,
  )
  print(f"{'SYMBOL':<24} | {'STRIKE':<8} | {'LTP':>7} | {'SPREAD':>6} | {'VOLUME':>9} | {'STATUS'}")
  print("-" * 78)

  recommended = []
  for _, sym, st, _ in selected:
    try:
      d = fetch_quote_fast(sym, exchange, timeout=3.0)
      if not d:
        print(f"{sym:<24} | {st:<8.0f} | {'N/A':>7} | {'-':>6} | {'-':>9} | NO DATA", flush=True)
        continue

      ltp = float(d.get("ltp", 0.0))
      bid = float(d.get("bid", ltp))
      ask = float(d.get("ask", ltp))
      spread = round(max(0.0, ask - bid), 2)
      vol = int(d.get("volume", 0))

      in_band = min_prem <= ltp <= max_prem
      tight_spread = spread <= 1.00
      status = "PASS (SWEET SPOT)" if (in_band and tight_spread) else "OUT OF BAND"
      if in_band and tight_spread:
        recommended.append(sym)

      print(f"{sym:<24} | {st:<8.0f} | {ltp:>7.2f} | {spread:>6.2f} | {vol:>9} | {status}", flush=True)
    except Exception as e:
      print(f"{sym:<24} | {st:<8.0f} | TIMEOUT/ERR: {e}", flush=True)
      break

  print("\n" + "=" * 78)
  if recommended:
    print("COPY-PASTE INTO config.py (Ordered Closest OTM -> Deeper OTM):")
    print(f"EXCHANGE = \"{exchange}\"")
    print(f"QTY = {lot_size}")
    print("CANDIDATE_STRIKES = [")
    for s in recommended[:5]:
      print(f"    \"{s}\",")
    print("]")
  else:
    print("[NOTE] No strikes fell inside ₹150–₹330 with <= ₹1.00 spread (or market closed).")


if __name__ == "__main__":
  run_strike_screener()
