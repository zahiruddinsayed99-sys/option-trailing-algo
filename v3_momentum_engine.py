import csv
import datetime
import os
import time
from broker_adapter import BrokerAdapter
import config

LOG_FILE = "v3_paper_trades_log.csv"
EXPECTED_HEADER = [
    "Timestamp",
    "Symbol",
    "Qty",
    "Entry_Price",
    "Exit_Price",
    "Highest_Price",
    "Highest_Stage",
    "Exit_Reason",
    "Gross_PnL",
    "Net_PnL",
    "Cumulative_Daily_PnL",
]
CANDLE_SEC = 180             # Strict 3-minute wall-clock candles
MAX_RISK_PER_TRADE = 500.0   # Dynamic ₹500 max risk per trade (25 pts SENSEX / 7.7 pts NIFTY)
CHASE_GUARD_PCT = 0.05       # Max 5% breakout extension above Base High
MAX_SPREAD_INDEX = 1.00      # Max ₹1.00 bid-ask spread for index options
MAX_SPREAD_STOCK = 0.15      # Max ₹0.15 bid-ask spread for stock options
MIN_OBSERVE_CANDLES = 4      # Minimum 4 candles (12 mins) if started late
MAX_QUOTE_FAILURES = 10      # Circuit breaker threshold (~20-30s dead feed)


def init_csv():
  """Ensures 11-column schema compliance and loads today's realized P&L/trades on restart."""
  needs_header = True
  if os.path.isfile(LOG_FILE):
    try:
      with open(LOG_FILE, mode="r", newline="") as f:
        first_line = f.readline().strip()
        if first_line == ",".join(EXPECTED_HEADER):
          needs_header = False
        else:
          backup_file = f"{LOG_FILE}.legacy.{int(time.time())}.bak"
          print(f"[CSV NOTICE] Legacy header detected. Archiving old log to {backup_file}")
          os.rename(LOG_FILE, backup_file)
    except Exception as e:
      print(f"[CSV WARNING] Could not inspect {LOG_FILE}: {e}")

  if needs_header:
    with open(LOG_FILE, mode="w", newline="") as f:
      writer = csv.writer(f)
      writer.writerow(EXPECTED_HEADER)
      f.flush()
      os.fsync(f.fileno())

  # Recover today's cumulative P&L and trade count so restarts never bypass daily kill-switches
  today_prefix = datetime.date.today().strftime("%Y-%m-%d")
  recovered_pnl = 0.0
  recovered_trades = 0
  try:
    with open(LOG_FILE, mode="r", newline="") as f:
      reader = csv.DictReader(f)
      for row in reader:
        ts = str(row.get("Timestamp", ""))
        if ts.startswith(today_prefix):
          recovered_trades += 1
          recovered_pnl += float(row.get("Net_PnL", 0) or 0)
  except Exception:
    pass
  return round(recovered_pnl, 2), recovered_trades


def log_trade(row):
  """Atomic CSV append with retry protection against Windows/Excel file locks."""
  for _ in range(3):
    try:
      with open(LOG_FILE, mode="a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(row)
        f.flush()
        os.fsync(f.fileno())
      return
    except PermissionError:
      print(f"[CSV RETRY] {LOG_FILE} locked by another process (e.g. Excel). Retrying in 1s...")
      time.sleep(1.0)
  print(f"[CRITICAL CSV ERROR] Failed to write trade row after 3 attempts: {row}")


def compute_ema(closes, period=9):
  if not closes:
    return 0.0
  k = 2.0 / (period + 1)
  ema = closes[0]
  for c in closes[1:]:
    ema = (c * k) + (ema * (1.0 - k))
  return ema


def current_candle_bucket():
  now = datetime.datetime.now()
  return (now.hour * 3600 + now.minute * 60 + now.second) // CANDLE_SEC


def sync_strike_history(broker, state, sym, exchange):
  """Hydrates Freeze-Hour (10:30-11:30 AM) base_high/base_low on OTM rotation."""
  st = state[sym]
  if st["base_high"] is not None:
    return
  bh, bl, hist_candles = broker.fetch_freeze_hour_base(sym, exchange)
  if bh is not None and bl is not None:
    st["base_high"] = bh
    st["base_low"] = bl
    if hist_candles:
      st["candles"] = hist_candles
    print(
        f"[BASE SYNCED | {sym}] Hydrated Freeze-Hour Base from history:"
        f" [{bl:.2f} - {bh:.2f}] ({len(hist_candles)} candles)"
    )


def run_v3_engine():
  daily_pnl, trades_today = init_csv()
  broker = BrokerAdapter()

  default_list = getattr(config, "CANDIDATE_STRIKES", [config.SYMBOL])
  default_str = ",".join(default_list)

  print("\n=== V3.4 HARDENED MULTI-STRIKE MOMENTUM ENGINE SETUP ===")
  sym_in = input(f"Candidate Strikes [{default_str}]: ").strip().upper()
  strikes = [s.strip() for s in sym_in.split(",") if s.strip()] if sym_in else default_list

  exch_in = input(f"Exchange [{config.EXCHANGE}]: ").strip().upper()
  exchange = exch_in if exch_in else config.EXCHANGE

  qty_in = input(f"Quantity [{config.QTY}]: ").strip()
  qty = int(qty_in) if qty_in else int(config.QTY)

  # Dynamic capital-normalized premium band & ₹500 max risk SL cap
  min_cap = getattr(config, "MIN_CAPITAL_PER_LOT", 4000.0)
  max_cap = getattr(config, "MAX_CAPITAL_PER_LOT", 5500.0)
  min_prem = round(min_cap / qty, 2)
  max_prem = round(max_cap / qty, 2)
  max_sl_points = round(MAX_RISK_PER_TRADE / qty, 2)
  charges_per_trade = getattr(config, "ESTIMATED_CHARGES_PER_TRADE", 55.0)
  cost_buffer_pts = round((charges_per_trade / qty) + 0.15, 2)

  max_spread = (
      MAX_SPREAD_INDEX
      if any(k in strikes[0] for k in ("NIFTY", "SENSEX", "BANKNIFTY"))
      else MAX_SPREAD_STOCK
  )

  state = {
      s: {
          "ticks": [],
          "candles": [],
          "base_high": None,
          "base_low": None,
          "base_locked": False,
          "last_quote": None,
      }
      for s in strikes
  }

  active_idx = 0
  active_sym = strikes[active_idx]
  started_late = datetime.datetime.now().time() >= datetime.time(11, 18)

  in_trade = False
  entry_price = 0.0
  initial_risk_pts = 0.0
  breakeven_trigger = 0.0
  profit_lock_trigger = 0.0
  highest_price = 0.0
  stop_loss = 0.0
  stage = "IDLE"
  climax_armed = False
  climax_trigger_price = None

  consecutive_quote_failures = 0
  last_rotation_check_ts = 0.0
  max_trades = getattr(config, "MAX_TRADES_PER_DAY", 3)
  max_daily_loss = getattr(config, "MAX_DAILY_LOSS", -800.0)

  last_bucket = current_candle_bucket()
  discard_first_partial_bucket = config.MODE != "SIMULATION"
  sim_ticks_in_bucket = 0

  print(
      f"\n>>> Starting V3.4 Engine [{config.MODE}] | {len(strikes)} Strikes Watched"
      f" | Band (₹{min_cap:.0f}-₹{max_cap:.0f}/lot): ₹{min_prem:.2f}-₹{max_prem:.2f}"
      f" | Max SL: {max_sl_points:.2f} pts | Today's Resume: {trades_today}/{max_trades} trades (₹{daily_pnl:.2f}) <<<"
  )

  try:
    while True:
      now = datetime.datetime.now()
      now_t = now.time()

      # 1. Daily Kill-Switch Guard
      if trades_today >= max_trades:
        print(f"\n[DAILY LIMIT REACHED] {trades_today}/{max_trades} trades executed today. Stopping.")
        break
      if daily_pnl <= max_daily_loss:
        print(f"\n[KILL SWITCH TRIGGERED] Daily P&L ₹{daily_pnl:.2f} <= ₹{max_daily_loss:.2f}. Halting.")
        break

      # 2. Time Windows
      if config.MODE == "SIMULATION":
        observe_start = datetime.time(0, 0)
        window_start = datetime.time(0, 0)
        window_end = datetime.time(23, 59)
        eod_exit_time = datetime.time(23, 59)
      else:
        observe_start = datetime.time(10, 30)
        window_start = datetime.time(11, 30)
        window_end = datetime.time(13, 30)
        eod_exit_time = datetime.time(15, 15)

      if not in_trade and now_t >= window_end:
        print(f"\n[WINDOW CLOSED] Past {window_end.strftime('%H:%M')} entry cutoff with no open position.")
        break

      # 3. Poll active strike (WebSocket primary + REST fallback + Verified Failsafe Exit)
      q = broker.get_quote(active_sym, exchange)
      if q:
        consecutive_quote_failures = 0
        state[active_sym]["last_quote"] = q
        state[active_sym]["ticks"].append(q["ltp"])
        if not in_trade and now_t < window_start:
          sp_txt = f"₹{q['spread']:.2f}" if q.get("valid_depth", True) else "NO_DEPTH"
          print(
              f"  [LIVE TICK] {active_sym} LTP: ₹{q['ltp']:.2f} | Spread: {sp_txt}   ",
              end="\r",
              flush=True,
          )
      else:
        consecutive_quote_failures += 1
        if consecutive_quote_failures >= MAX_QUOTE_FAILURES:
          print(f"\n[CRITICAL FEED ALERT] {consecutive_quote_failures} consecutive quote failures on {active_sym}!")
          if in_trade:
            print("[FAIL-SAFE EXIT] Attempting immediate MARKET exit due to broken data feed...")
            exit_resp = broker.place_market_order(active_sym, exchange, "SELL", qty)
            if exit_resp and exit_resp.get("status") == "success":
              last_ltp = (
                  state[active_sym]["last_quote"]["ltp"]
                  if state[active_sym]["last_quote"]
                  else entry_price
              )
              exit_px = exit_resp["fill_price"] if exit_resp["fill_price"] > 0 else last_ltp
              gross = round((exit_px - entry_price) * qty, 2)
              net = round(gross - charges_per_trade, 2)
              daily_pnl = round(daily_pnl + net, 2)
              trades_today += 1
              log_trade([
                  now.strftime("%Y-%m-%d %H:%M:%S"),
                  active_sym,
                  qty,
                  round(entry_price, 2),
                  round(exit_px, 2),
                  round(highest_price, 2),
                  stage,
                  "FEED_FAILURE_FAILSAFE",
                  gross,
                  net,
                  daily_pnl,
              ])
              in_trade = False
              stage = "IDLE"
              climax_armed = False
              climax_trigger_price = None
              state[active_sym]["base_locked"] = False
              state[active_sym]["candles"].clear()
              state[active_sym]["base_high"] = None
              state[active_sym]["base_low"] = None
            else:
              print(
                  f"[FATAL ORDER ALERT] Failsafe SELL failed for {active_sym}!"
                  " Position STILL OPEN at broker — keeping in_trade=True and retrying!"
              )
          consecutive_quote_failures = 0
        time.sleep(2.0)
        continue

      # 4. Dynamic OTM Strike Auto-Rotation (with 15s cooldown to prevent 429 sweeps)
      if (
          not in_trade
          and len(strikes) > 1
          and state[active_sym]["last_quote"]
          and (time.time() - last_rotation_check_ts) >= 15.0
      ):
        curr_ltp = state[active_sym]["last_quote"]["ltp"]
        if curr_ltp > max_prem and active_idx + 1 < len(strikes):
          last_rotation_check_ts = time.time()
          for next_i in range(active_idx + 1, len(strikes)):
            cand_s = strikes[next_i]
            time.sleep(0.5)
            cand_q = broker.get_quote(cand_s, exchange)
            state[cand_s]["last_quote"] = cand_q
            if (
                cand_q
                and cand_q.get("valid_depth", True)
                and cand_q["ltp"] <= max_prem
                and cand_q["spread"] <= max(max_spread, round(cand_q["ltp"] * 0.005, 2))
            ):
              print(
                  f"\n>>> [OTM ROTATE UP] {active_sym} LTP ₹{curr_ltp:.2f} > ₹{max_prem:.2f}."
                  f" Switching to {cand_s} @ ₹{cand_q['ltp']:.2f} <<<"
              )
              state[active_sym]["ticks"].clear()
              active_idx = next_i
              active_sym = cand_s
              sync_strike_history(broker, state, active_sym, exchange)
              break
        elif curr_ltp < min_prem and active_idx - 1 >= 0:
          last_rotation_check_ts = time.time()
          for prev_i in range(active_idx - 1, -1, -1):
            cand_s = strikes[prev_i]
            time.sleep(0.5)
            cand_q = broker.get_quote(cand_s, exchange)
            state[cand_s]["last_quote"] = cand_q
            if (
                cand_q
                and cand_q.get("valid_depth", True)
                and min_prem <= cand_q["ltp"] <= max_prem
                and cand_q["spread"] <= max(max_spread, round(cand_q["ltp"] * 0.005, 2))
            ):
              print(
                  f"\n>>> [OTM ROTATE DOWN] {active_sym} LTP ₹{curr_ltp:.2f} < ₹{min_prem:.2f}."
                  f" Switching back to {cand_s} @ ₹{cand_q['ltp']:.2f} <<<"
              )
              state[active_sym]["ticks"].clear()
              active_idx = prev_i
              active_sym = cand_s
              sync_strike_history(broker, state, active_sym, exchange)
              break

      # 5. Intra-Candle Tick Exit Management
      if in_trade and state[active_sym]["last_quote"]:
        ltp = state[active_sym]["last_quote"]["ltp"]
        if ltp > highest_price:
          highest_price = ltp

        # Stage 1: 1:1.5 Risk-Reward Cost-Adjusted Breakeven Lock
        if stage == "INITIAL_BASE_SL" and ltp >= breakeven_trigger:
          be_with_charges = round(entry_price + cost_buffer_pts, 2)
          stop_loss = max(stop_loss, be_with_charges)
          stage = "STAGE1_1.5R_BREAKEVEN"
          print(
              f"\n[STAGE 1: 1.5R BREAKEVEN] {active_sym} hit ₹{ltp:.2f} (>= ₹{breakeven_trigger:.2f})."
              f" SL locked at Net Cost: ₹{stop_loss:.2f}"
          )

        # Stage 1.5: 1:2.5 Risk-Reward -> Lock +1R Guaranteed Profit Floor
        if stage in ("INITIAL_BASE_SL", "STAGE1_1.5R_BREAKEVEN") and ltp >= profit_lock_trigger:
          one_r_floor = round(entry_price + initial_risk_pts, 2)
          stop_loss = max(stop_loss, one_r_floor)
          stage = "STAGE1.5_2.5R_LOCK_1R"
          print(
              f"\n[STAGE 1.5: 2.5R PROFIT LOCK] {active_sym} hit ₹{ltp:.2f} (>= ₹{profit_lock_trigger:.2f})."
              f" SL locked at +1R: ₹{stop_loss:.2f}"
          )

        # Stage 2: +50% Profit Surge -> Lock +25% Floor
        if ltp >= entry_price * 1.50 and stage != "STAGE2_PROFIT_TRAIL":
          stop_loss = max(stop_loss, round(entry_price * 1.25, 2))
          stage = "STAGE2_PROFIT_TRAIL"
          print(
              f"\n[STAGE 2: +50% SURGE] {active_sym} hit ₹{ltp:.2f}."
              f" Floor SL locked at +25%: ₹{stop_loss:.2f}"
          )

        exit_reason = None
        if ltp <= stop_loss:
          exit_reason = f"STOP_LOSS ({stage})"
        elif ltp >= entry_price * 2.00:
          exit_reason = "TARGET_2X_DOUBLED"
        elif now_t >= eod_exit_time:
          exit_reason = "EOD_SQUARE_OFF"

        if exit_reason:
          exit_resp = broker.place_market_order(active_sym, exchange, "SELL", qty)
          if exit_resp and exit_resp.get("status") == "success":
            exit_px = exit_resp["fill_price"] if exit_resp["fill_price"] > 0 else ltp
            gross = round((exit_px - entry_price) * qty, 2)
            net = round(gross - charges_per_trade, 2)
            daily_pnl = round(daily_pnl + net, 2)
            trades_today += 1
            print(
                f"\n[EXIT EXECUTED] {active_sym} @ ₹{exit_px:.2f} | Reason: {exit_reason}"
                f" | Net P&L: ₹{net:.2f} | Daily P&L: ₹{daily_pnl:.2f} | Trades: {trades_today}/{max_trades}"
            )
            log_trade([
                now.strftime("%Y-%m-%d %H:%M:%S"),
                active_sym,
                qty,
                round(entry_price, 2),
                round(exit_px, 2),
                round(highest_price, 2),
                stage,
                exit_reason,
                gross,
                net,
                daily_pnl,
            ])
            in_trade = False
            stage = "IDLE"
            climax_armed = False
            climax_trigger_price = None
            state[active_sym]["base_locked"] = False
            state[active_sym]["candles"].clear()
            state[active_sym]["base_high"] = None
            state[active_sym]["base_low"] = None
            continue
          else:
            print(f"[EXIT RETRY ALERT] SELL order rejected for {active_sym} on {exit_reason} — will retry next tick!")

      # 6. Check 3-Minute Candle Close Boundary
      sim_ticks_in_bucket += 1
      if config.MODE == "SIMULATION":
        candle_closed = sim_ticks_in_bucket >= 4
      else:
        curr_bucket = current_candle_bucket()
        candle_closed = curr_bucket != last_bucket
        if candle_closed:
          last_bucket = curr_bucket

      if candle_closed:
        sim_ticks_in_bucket = 0
        st = state[active_sym]
        if not st["ticks"]:
          continue

        if discard_first_partial_bucket:
          discard_first_partial_bucket = False
          st["ticks"].clear()
          print("\n[SYNC] Discarded truncated startup candle; aligned to clean 3-minute boundary.")
          continue

        c_open = st["ticks"][0]
        c_high = max(st["ticks"])
        c_low = min(st["ticks"])
        c_close = st["ticks"][-1]
        st["ticks"].clear()

        # Ignore pre-10:30 AM opening bell spikes
        if now_t < observe_start:
          continue

        candle = {"open": c_open, "high": c_high, "low": c_low, "close": c_close}
        st["candles"].append(candle)
        closes = [c["close"] for c in st["candles"]]
        ema9 = compute_ema(closes, period=9)

        need_warmup = (
            st["base_high"] is None
            or (started_late and len(st["candles"]) <= MIN_OBSERVE_CANDLES)
        )

        # PHASE A: Bounded Freeze-Hour Base Observation (10:30 - 11:30 AM)
        if now_t < window_start or need_warmup:
          st["base_high"] = (
              c_high if st["base_high"] is None else max(st["base_high"], c_high)
          )
          st["base_low"] = (
              c_low if st["base_low"] is None else min(st["base_low"], c_low)
          )
          print(
              f"\n[BASE OBSERVE #{len(st['candles'])} | {active_sym}]"
              f" Close: {c_close:.2f} | Base: [{st['base_low']:.2f} - {st['base_high']:.2f}]"
          )

        # PHASE B: Active Entry Hunting (11:30 AM - 01:30 PM)
        elif not in_trade:
          if not st["base_locked"]:
            st["base_locked"] = True
            print(
                f"\n>>> [BASE LOCKED | {active_sym}] High: {st['base_high']:.2f}"
                f" | Low: {st['base_low']:.2f} | Hunting Breakouts <<<"
            )

          valid_depth = st["last_quote"].get("valid_depth", True) if st["last_quote"] else False
          spread_now = st["last_quote"]["spread"] if st["last_quote"] else 999.0
          sp_disp = f"₹{spread_now:.2f}" if valid_depth else "NO_DEPTH"
          print(
              f"[SCANNING 3M | {active_sym}] Close: {c_close:.2f}"
              f" | Base High: {st['base_high']:.2f} | 9 EMA: {ema9:.2f} | Spread: {sp_disp}"
          )

          if c_close > st["base_high"]:
            chase_limit = st["base_high"] * (1.0 + CHASE_GUARD_PCT)
            if not valid_depth:
              print("[SKIP BREAKOUT] Missing live bid/ask depth.")
            elif c_close > chase_limit:
              print(
                  f"[SKIP BREAKOUT] Close {c_close:.2f} > 5% Chase Guard ({chase_limit:.2f})."
              )
            elif spread_now > max(max_spread, round(c_close * 0.005, 2)):
              eff_spread = max(max_spread, round(c_close * 0.005, 2))
              print(
                  f"[SKIP BREAKOUT] Spread ₹{spread_now:.2f} > Max ₹{eff_spread:.2f}."
              )
            else:
              order_resp = broker.place_market_order(active_sym, exchange, "BUY", qty)
              if order_resp and order_resp.get("status") == "success":
                in_trade = True
                entry_price = (
                    order_resp["fill_price"]
                    if order_resp["fill_price"] > 0
                    else c_close
                )
                highest_price = entry_price

                raw_sl_pts = entry_price - st["base_low"]
                if raw_sl_pts <= 0 or raw_sl_pts > max_sl_points:
                  stop_loss = round(entry_price - max_sl_points, 2)
                else:
                  stop_loss = round(st["base_low"], 2)

                initial_risk_pts = round(entry_price - stop_loss, 2)
                breakeven_trigger = round(entry_price + (1.5 * initial_risk_pts), 2)
                profit_lock_trigger = round(entry_price + (2.5 * initial_risk_pts), 2)
                stage = "INITIAL_BASE_SL"
                climax_armed = False
                climax_trigger_price = None
                print(
                    f"\n>>> [ENTRY TRIGGERED] BUY {qty} {active_sym} @ ₹{entry_price:.2f}"
                    f" | SL: ₹{stop_loss:.2f} (Risk: {initial_risk_pts:.2f} pts / ₹{initial_risk_pts*qty:.0f})"
                    f" | 1.5R BE: ₹{breakeven_trigger:.2f} | 2.5R +1R Lock: ₹{profit_lock_trigger:.2f} <<<"
                )

        # PHASE C: Candle-Close Trailing & Momentum Exit
        else:
          candles = st["candles"]
          if stage == "STAGE2_PROFIT_TRAIL" and len(candles) >= 2:
            two_candle_low = min(candles[-1]["low"], candles[-2]["low"])
            if two_candle_low > stop_loss:
              stop_loss = round(two_candle_low, 2)
              print(f"[STAGE 2 TRAIL] 2-Candle Low SL raised to ₹{stop_loss:.2f}")

          # 1-Candle Climax Wick Verification (auto-disarms if next candle holds above trigger)
          if climax_armed:
            if c_close < climax_trigger_price:
              exit_resp = broker.place_market_order(active_sym, exchange, "SELL", qty)
              if exit_resp and exit_resp.get("status") == "success":
                exit_px = exit_resp["fill_price"] if exit_resp["fill_price"] > 0 else c_close
                gross = round((exit_px - entry_price) * qty, 2)
                net = round(gross - charges_per_trade, 2)
                daily_pnl = round(daily_pnl + net, 2)
                trades_today += 1
                print(f"\n[CLIMAX EXIT] {active_sym} @ ₹{exit_px:.2f} | Net P&L: ₹{net:.2f}")
                log_trade([
                    now.strftime("%Y-%m-%d %H:%M:%S"),
                    active_sym,
                    qty,
                    round(entry_price, 2),
                    round(exit_px, 2),
                    round(highest_price, 2),
                    stage,
                    "CLIMAX_WICK_EXIT",
                    gross,
                    net,
                    daily_pnl,
                ])
                in_trade = False
                stage = "IDLE"
                climax_armed = False
                climax_trigger_price = None
                state[active_sym]["base_locked"] = False
                state[active_sym]["candles"].clear()
                state[active_sym]["base_high"] = None
                state[active_sym]["base_low"] = None
                continue
            else:
              print(
                  f"[CLIMAX WICK DISARMED] Close {c_close:.2f} >= {climax_trigger_price:.2f}."
                  " Trend intact."
              )
              climax_armed = False
              climax_trigger_price = None

          # Arm Climax Wick ONLY for the immediately following candle
          body = abs(c_close - c_open)
          upper_wick = c_high - max(c_open, c_close)
          candle_range = c_high - c_low
          if (
              candle_range > 0
              and body > 0
              and upper_wick >= (2.0 * body)
              and upper_wick >= (0.50 * candle_range)
              and c_close > entry_price * 1.25
          ):
            climax_armed = True
            climax_trigger_price = c_low
            print(
                f"[CLIMAX WICK ARMED] Exit armed ONLY for next candle if close < {climax_trigger_price:.2f}"
            )

          if stage == "STAGE2_PROFIT_TRAIL" and len(closes) >= 9 and c_close < ema9:
            exit_resp = broker.place_market_order(active_sym, exchange, "SELL", qty)
            if exit_resp and exit_resp.get("status") == "success":
              exit_px = exit_resp["fill_price"] if exit_resp["fill_price"] > 0 else c_close
              gross = round((exit_px - entry_price) * qty, 2)
              net = round(gross - charges_per_trade, 2)
              daily_pnl = round(daily_pnl + net, 2)
              trades_today += 1
              print(
                  f"\n[STAGE 3: 9 EMA EXIT] {active_sym} closed ₹{c_close:.2f} < 9 EMA ₹{ema9:.2f}"
                  f" | Net P&L: ₹{net:.2f}"
              )
              log_trade([
                  now.strftime("%Y-%m-%d %H:%M:%S"),
                  active_sym,
                  qty,
                  round(entry_price, 2),
                  round(exit_px, 2),
                  round(highest_price, 2),
                  stage,
                  "9_EMA_MOMENTUM_EXIT",
                  gross,
                  net,
                  daily_pnl,
              ])
              in_trade = False
              stage = "IDLE"
              climax_armed = False
              climax_trigger_price = None
              state[active_sym]["base_locked"] = False
              state[active_sym]["candles"].clear()
              state[active_sym]["base_high"] = None
              state[active_sym]["base_low"] = None
              continue

      if in_trade and state[active_sym]["last_quote"]:
        ltp = state[active_sym]["last_quote"]["ltp"]
        unrealized = round((ltp - entry_price) * qty, 2)
        pct = ((ltp - entry_price) / entry_price) * 100.0
        print(
            f"[{stage} | {active_sym}] LTP: {ltp:.2f} ({pct:+.1f}%)"
            f" | SL: {stop_loss:.2f} | 1.5R BE: {breakeven_trigger:.2f} | P&L: ₹{unrealized:.1f}"
        )

      time.sleep(0.3 if config.MODE == "SIMULATION" else 1.5)

  except KeyboardInterrupt:
    print("\n[STOPPED] Engine manually terminated by user.")
  finally:
    broker.shutdown()


if __name__ == "__main__":
  run_v3_engine()