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
  print("\n=== V3.4 INSTANT PRE-MARKET STRIKE SCREENER ===")
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
  # Read-only URI mode prevents SQLite lock contention with live OpenAlgo server
  conn = sqlite3.connect(f"file:{OPENALGO_DB}?mode=ro", uri=True)
  cur = conn.cursor()
  cur.execute(
      """
      SELECT symbol, expiry, strike, lotsize
      FROM symtoken
      WHERE exchange = ? AND name = ? AND instrumenttype = ? AND symbol LIKE ?
      """,
      (exchange, idx_in, opt_in, f"{idx_in}%{opt_in}"),
  )
  rows = cur.fetchall()
  conn.close()

  if not rows:
    print(f"[ERROR] No {idx_in} {opt_in} contracts found in OpenAlgo master DB.")
    return

  now = datetime.datetime.now()
  today = now.date()
  # If run after 15:30 IST, exclude today's expired contracts
  min_valid_date = today + datetime.timedelta(days=1) if now.time() >= datetime.time(15, 30) else today

  valid_rows = []
  for sym, exp_str, strike, lotsize in rows:
    exp_dt = parse_expiry(exp_str)
    if exp_dt and exp_dt >= min_valid_date:
      valid_rows.append((exp_dt, exp_str, sym, float(strike), int(lotsize)))

  if not valid_rows:
    print("[ERROR] No active/upcoming expiries found.")
    return

  distinct_expiries = sorted(set(r[0] for r in valid_rows))
  selected_exp = distinct_expiries[0]

  # 0-DTE Expiry-Day Gamma/Theta Guardrail
  if selected_exp == today and len(distinct_expiries) > 1:
    next_exp = distinct_expiries[1]
    print(f"\n[0-DTE EXPIRY WARNING] Nearest expiry ({selected_exp}) is TODAY!")
    print("  On 0-DTE, ₹4K-₹5K/lot forces Deep ITM strikes with wide spreads & extreme gamma.")
    choice = input(f"  Switch to Next-Week Expiry ({next_exp})? [Y/n]: ").strip().lower()
    if choice != "n":
      selected_exp = next_exp

  expiry_contracts = [r for r in valid_rows if r[0] == selected_exp]
  exp_str = expiry_contracts[0][1]

  # Index-aware ATM offset (200 pts SENSEX vs 100 pts NIFTY)
  offset = 200 if idx_in == "SENSEX" else 100
  if opt_in == "CE":
    otm = sorted([r for r in expiry_contracts if r[3] >= spot - offset], key=lambda x: x[3])[:10]
  else:
    otm = sorted([r for r in expiry_contracts if r[3] <= spot + offset], key=lambda x: x[3], reverse=True)[:10]

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
        raw_bid = float(d.get("bid", 0) or 0)
        raw_ask = float(d.get("ask", 0) or 0)
        valid_depth = raw_bid > 0 and raw_ask > 0 and raw_ask >= raw_bid
        spread = round(raw_ask - raw_bid, 2) if valid_depth else 999.0
        cap_req = round(ltp * lot_size, 0)

        if not valid_depth:
          status = "NO DEPTH"
        elif min_prem <= ltp <= max_prem and spread <= 1.00:
          status = "SWEET SPOT"
          sweet_spot.append(sym)
        elif ltp > max_prem:
          status = "EXPENSIVE (>₹5K)"
        elif ltp < min_prem:
          status = "DEEP OTM (<₹4K)"
        else:
          status = "WIDE SPREAD"

        spread_disp = f"₹{spread:<6.2f}" if valid_depth else "N/A    "
        print(
            f"{sym:<24} | {strike:<8.0f} | ₹{ltp:<7.2f} | ₹{cap_req:<10.0f} | {spread_disp} | {status}",
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
        f" (₹{min_cap:.0f}-₹{max_cap:.0f}/lot) with valid depth & <= ₹1.00 spread."
    )
  print("=" * 82 + "\n")


if __name__ == "__main__":
  screen_strikes()