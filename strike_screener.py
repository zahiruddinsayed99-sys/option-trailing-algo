import datetime
import os
import sqlite3
import time
import config
from openalgo import api

OPENALGO_DB = os.path.expanduser("~/trading-projects/openalgo/db/openalgo.db")


def parse_expiry(exp_str):
  for fmt in ("%d-%b-%y", "%d-%b-%Y", "%Y-%m-%d"):
    try:
      return datetime.datetime.strptime(exp_str.strip(), fmt).date()
    except ValueError:
      continue
  return None


def screen_strikes():
  print("\n=== V3.2 INSTANT PRE-MARKET STRIKE SCREENER ===")
  idx_in = input("Index [SENSEX / NIFTY] (default SENSEX): ").strip().upper() or "SENSEX"
  opt_in = input("Direction [CE / PE] (default PE): ").strip().upper() or "PE"
  spot_str = input("Current Spot Level (e.g., 83300 for SENSEX, 24150 for NIFTY): ").strip()

  if not spot_str:
    print("[ERROR] Spot level is required to filter nearby OTM strikes.")
    return
  spot = float(spot_str)

  exchange = "BFO" if idx_in == "SENSEX" else "NFO"
  min_cap = getattr(config, "MIN_CAPITAL_PER_LOT", 4000.0)
  max_cap = getattr(config, "MAX_CAPITAL_PER_LOT", 5000.0)
  lot_preview = 20 if idx_in == "SENSEX" else 65

  if not os.path.isfile(OPENALGO_DB):
    print(f"[ERROR] OpenAlgo SQLite master database not found at {OPENALGO_DB}")
    return

  t0 = time.time()
  conn = sqlite3.connect(OPENALGO_DB)
  cur = conn.cursor()
  cur.execute(
      """
      SELECT symbol, expiry, strike, lotsize
      FROM symtoken
      WHERE exchange = ? AND name = ? AND instrumenttype = 'OPTIDX' AND symbol LIKE ?
      """,
      (exchange, idx_in, f"%{opt_in}"),
  )
  rows = cur.fetchall()
  conn.close()

  if not rows:
    print(f"[ERROR] No {idx_in} {opt_in} contracts found in OpenAlgo master DB.")
    return

  today = datetime.date.today()
  valid_rows = []
  for sym, exp_str, strike, lotsize in rows:
    exp_dt = parse_expiry(exp_str)
    if exp_dt and exp_dt >= today:
      valid_rows.append((exp_dt, exp_str, sym, float(strike), int(lotsize)))

  if not valid_rows:
    print("[ERROR] No active/upcoming expiries found.")
    return

  nearest_exp = min(r[0] for r in valid_rows)
  expiry_contracts = [r for r in valid_rows if r[0] == nearest_exp]
  exp_str = expiry_contracts[0][1]

  # Pick 10 strikes starting near ATM into OTM
  if opt_in == "CE":
    otm = sorted([r for r in expiry_contracts if r[3] >= spot - 100], key=lambda x: x[3])[:10]
  else:
    otm = sorted([r for r in expiry_contracts if r[3] <= spot + 100], key=lambda x: x[3], reverse=True)[:10]

  lot_size = otm[0][4] if otm else lot_preview
  min_prem = round(min_cap / lot_size, 2)
  max_prem = round(max_cap / lot_size, 2)

  print(
      f"\n[DB LOOKUP: {time.time()-t0:.3f}s] Expiry: {exp_str} | Lot: {lot_size}"
      f" | Band (₹{min_cap:.0f}-₹{max_cap:.0f}/lot): ₹{min_prem:.2f}-₹{max_prem:.2f}"
      f" | Checking {len(otm)} strikes...\n",
      flush=True,
  )

  client = api(api_key=config.OPENALGO_API_KEY, host=config.OPENALGO_HOST)
  sweet_spot = []

  print(f"{'SYMBOL':<24} | {'STRIKE':<8} | {'LTP':<8} | {'CAPITAL/LOT':<11} | {'SPREAD':<7} | {'STATUS'}")
  print("-" * 82)

  for _, _, sym, strike, _ in otm:
    time.sleep(1.1)
    try:
      q = client.quotes(symbol=sym, exchange=exchange)
      if isinstance(q, dict) and q.get("status") == "success" and "data" in q:
        d = q["data"]
        ltp = float(d["ltp"])
        bid = float(d.get("bid", ltp))
        ask = float(d.get("ask", ltp))
        spread = round(max(0.0, ask - bid), 2)
        cap_req = round(ltp * lot_size, 0)

        if min_prem <= ltp <= max_prem and spread <= 1.00:
          status = "SWEET SPOT"
          sweet_spot.append(sym)
        elif ltp > max_prem:
          status = "EXPENSIVE (>₹5K)"
        elif ltp < min_prem:
          status = "DEEP OTM (<₹4K)"
        else:
          status = "WIDE SPREAD"

        print(
            f"{sym:<24} | {strike:<8.0f} | ₹{ltp:<7.2f} | ₹{cap_req:<10.0f} | ₹{spread:<6.2f} | {status}",
            flush=True,
        )
    except Exception as e:
      print(f"{sym:<24} | {strike:<8.0f} | ERROR: {e}", flush=True)

  print("\n" + "=" * 82)
  if sweet_spot:
    print("RECOMMENDED CANDIDATE_STRIKES FOR config.py:")
    print(f"CANDIDATE_STRIKES = {sweet_spot[:5]}")
  else:
    print(
        f"[NOTE] No strikes fell inside ₹{min_prem:.2f}–₹{max_prem:.2f}"
        f" (₹{min_cap:.0f}-₹{max_cap:.0f}/lot) with <= ₹1.00 spread (or market closed)."
    )
  print("=" * 82 + "\n")


if __name__ == "__main__":
  screen_strikes()