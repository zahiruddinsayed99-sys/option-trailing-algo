import csv
import datetime
import os
import sys
import time
from broker_adapter import BrokerAdapter
import config
from equity_screener import select_trending_sensex_stocks

LOG_FILE = "equity_paper_trades_log.csv"
EXPECTED_HEADER = [
    "Timestamp",
    "Symbol",
    "Direction",
    "Qty",
    "Entry_Price",
    "Exit_Price",
    "Stop_Loss",
    "Highest_Stage",
    "Exit_Reason",
    "Gross_PnL",
    "Net_PnL",
    "Cumulative_Daily_PnL",
]
CANDLE_SEC = 180              # Strict 3-minute wall-clock candles
CHASE_GUARD_LONG = 1.015     # Max 1.5% breakout extension above Base High
CHASE_GUARD_SHORT = 0.985    # Max 1.5% breakdown extension below Base Low
MAX_STRUCTURAL_STOP_PCT = 0.008  # Max 0.8% structural stop distance
MAX_SPREAD_PCT = 0.10        # Max 0.10% bid-ask spread
VOLUME_SURGE_MULTIPLIER = 1.5  # Min 1.5x rolling 10-candle volume surge
MAX_QUOTE_FAILURES = 10      # Stale-feed circuit breaker threshold (~20-30s dead feed)


def _parse_hhmm(hhmm_str, default_time):
  """Safely parses 'HH:MM' config strings into datetime.time objects."""
  try:
    h, m = map(int, str(hhmm_str).strip().split(":"))
    return datetime.time(h, m)
  except Exception:
    return default_time


def init_csv():
  """Ensures 12-column schema compliance and loads today's realized P&L/trades on restart."""
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
  for attempt in range(3):
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
  """Computes Exponential Moving Average over closed prices."""
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


def check_volume_surge(candles, current_vol):
  """Checks if current volume >= 1.5x rolling 10-candle average."""
  if not candles:
    return True
  prior = candles[-10:]
  avg_vol = sum(c.get("volume", 0) for c in prior) / len(prior) if prior else 0.0
  if avg_vol <= 0:
    return True
  return current_vol >= (VOLUME_SURGE_MULTIPLIER * avg_vol)


def hydrate_symbol_history(broker, sym, exchange):
  """Hydrates morning 3m candles from 09:15 AM, computing cumulative Session VWAP and configured Freeze Box boundaries."""
  hist_candles = broker.fetch_intraday_history(sym, exchange, interval="3m")
  sum_pv = 0.0
  sum_vol = 0.0
  base_high = None
  base_low = None

  obs_t = _parse_hhmm(getattr(config, "EQUITY_OBSERVE_START", "10:15"), datetime.time(10, 15))
  win_t = _parse_hhmm(getattr(config, "EQUITY_WINDOW_START", "11:00"), datetime.time(11, 0))

  for c in hist_candles:
    h = c["high"]
    l = c["low"]
    cl = c["close"]
    vol = c.get("volume", 0.0)
    typ_px = (h + l + cl) / 3.0
    sum_pv += typ_px * vol
    sum_vol += vol

    ts = c.get("timestamp", "")
    # Dynamically check if candle lies within configured Freeze Box (e.g., 10:15 - 11:00 AM)
    try:
      time_part = ts.split(" ")[1][:5] if " " in ts else ts[:5]
      c_time = _parse_hhmm(time_part, None)
    except Exception:
      c_time = None

    if c_time is not None and obs_t <= c_time < win_t:
      base_high = h if base_high is None else max(base_high, h)
      base_low = l if base_low is None else min(base_low, l)

  session_vwap = round(sum_pv / sum_vol, 2) if sum_vol > 0 else (hist_candles[-1]["close"] if hist_candles else 0.0)
  return hist_candles, sum_pv, sum_vol, session_vwap, base_high, base_low


def run_equity_engine(custom_symbols=None, custom_direction=None, headless=False):
  daily_pnl, trades_today = init_csv()
  broker = BrokerAdapter()

  max_trades = getattr(config, "EQUITY_MAX_TRADES_PER_DAY", 2)
  max_daily_loss = getattr(config, "EQUITY_MAX_DAILY_LOSS", -800.0)
  max_risk_trade = getattr(config, "EQUITY_MAX_RISK_PER_TRADE", 400.0)
  max_notional = getattr(config, "EQUITY_MAX_NOTIONAL", 25000.0)
  charges_per_trade = getattr(config, "EQUITY_ESTIMATED_CHARGES", 35.0)
  exchange = getattr(config, "EQUITY_EXCHANGE", "NSE")

  # Configurable Session Time Windows (IST)
  if config.MODE == "SIMULATION":
    observe_start = datetime.time(0, 0)
    window_start = datetime.time(0, 0)
    window_end = datetime.time(23, 59)
    eod_exit_time = datetime.time(23, 59)
  else:
    observe_start = _parse_hhmm(getattr(config, "EQUITY_OBSERVE_START", "10:15"), datetime.time(10, 15))
    window_start = _parse_hhmm(getattr(config, "EQUITY_WINDOW_START", "11:00"), datetime.time(11, 0))
    window_end = _parse_hhmm(getattr(config, "EQUITY_WINDOW_END", "13:30"), datetime.time(13, 30))
    eod_exit_time = _parse_hhmm(getattr(config, "EQUITY_EOD_EXIT", "15:10"), datetime.time(15, 10))

  # 1. Startup Guardrail Check
  if trades_today >= max_trades:
    print(f"\n[DAILY LIMIT REACHED] {trades_today}/{max_trades} trades executed today. Halting.")
    return
  if daily_pnl <= max_daily_loss:
    print(f"\n[KILL SWITCH TRIGGERED] Daily P&L ₹{daily_pnl:.2f} <= ₹{max_daily_loss:.2f}. Halting.")
    return

  # 2. Screener Execution & Candidate Selection
  if custom_symbols and custom_direction:
    direction = custom_direction.upper()
    watch_symbols = custom_symbols
    regime = "BULLISH" if direction == "LONG" else "BEARISH"
  else:
    regime, direction, screened_symbols = select_trending_sensex_stocks(broker)
    if regime == "SIDEWAYS" or not screened_symbols:
      if not headless and config.MODE != "SIMULATION":
        override = input("Market is SIDEWAYS. Manually override candidates? [y/N]: ").strip().lower()
        if override != "y":
          print("[ENGINE] Exiting per market regime standing-down protocol.")
          return
        dir_in = input("Direction [LONG/SHORT]: ").strip().upper()
        sym_in = input("Symbols (comma-separated): ").strip().upper()
        direction = dir_in if dir_in in ("LONG", "SHORT") else "LONG"
        watch_symbols = [s.strip() for s in sym_in.split(",") if s.strip()]
      else:
        print("[ENGINE] Standing down per market regime protocol.")
        return
    else:
      watch_symbols = screened_symbols

  if not headless and config.MODE != "SIMULATION":
    default_str = ",".join(watch_symbols)
    sym_in = input(f"Watchlist [{default_str}]: ").strip().upper()
    if sym_in:
      watch_symbols = [s.strip() for s in sym_in.split(",") if s.strip()]

  print("\n" + "=" * 80)
  print(f"   V1.0 NSE CASH EQUITY INTRADAY ENGINE [{config.MODE}]")
  print(f"   Direction: {direction} | Watchlist: {watch_symbols}")
  print(
      f"   Session Windows: Freeze Box [{observe_start.strftime('%H:%M')} - {window_start.strftime('%H:%M')}]"
      f" | Trade [{window_start.strftime('%H:%M')} - {window_end.strftime('%H:%M')}]"
  )
  print(f"   Max Risk/Trade: ₹{max_risk_trade:.2f} | Max Notional: ₹{max_notional:.2f} | Daily Loss Cap: ₹{max_daily_loss:.2f}")
  print(f"   Resume State: {trades_today}/{max_trades} trades executed today (P&L: ₹{daily_pnl:.2f})")
  print("=" * 80 + "\n")

  # 3. State Initialization & History Hydration
  state = {}
  for sym in watch_symbols:
    hist_c, sum_pv, sum_vol, vwap, bh, bl = hydrate_symbol_history(broker, sym, exchange)
    state[sym] = {
        "ticks": [],
        "candles": hist_c,
        "sum_pv": sum_pv,
        "sum_vol": sum_vol,
        "session_vwap": vwap,
        "base_high": bh,
        "base_low": bl,
        "candle_start_vol": 0.0,
        "last_quote": None,
    }
    bh_str = f"₹{bh:.2f}" if bh is not None else "PENDING"
    bl_str = f"₹{bl:.2f}" if bl is not None else "PENDING"
    print(f"[{sym}] Hydrated {len(hist_c)} 3m candles | Session VWAP: ₹{vwap:.2f} | Base: [{bl_str} - {bh_str}]")

  # Position & Execution tracking variables
  in_trade = False
  active_sym = None
  entry_price = 0.0
  stop_loss = 0.0
  initial_sl = 0.0
  risk_per_share = 0.0
  qty = 0
  stage = "IDLE"
  highest_stage = "IDLE"
  highest_price = 0.0
  lowest_price = 999999.0
  stage1_trigger = 0.0
  stage2_trigger = 0.0
  hard_target = 0.0
  cost_buffer_pts = 0.0

  consecutive_quote_failures = 0
  last_bucket = current_candle_bucket()
  discard_first_partial_bucket = config.MODE != "SIMULATION"
  sim_ticks_in_bucket = 0

  try:
    while True:
      now = datetime.datetime.now()
      now_t = now.time()

      # 4. Daily Kill-Switch Guard
      if trades_today >= max_trades:
        print(f"\n[DAILY LIMIT REACHED] {trades_today}/{max_trades} trades completed today. Stopping.")
        break
      if daily_pnl <= max_daily_loss:
        print(f"\n[KILL SWITCH TRIGGERED] Daily P&L ₹{daily_pnl:.2f} <= ₹{max_daily_loss:.2f}. Halting.")
        break

      # 5. EOD MIS Square-Off check
      if in_trade and now_t >= eod_exit_time:
        print(f"\n[EOD MIS SQUARE-OFF] {eod_exit_time.strftime('%H:%M')} IST cutoff reached. Closing active {direction} position...")
        exit_action = "SELL" if direction == "LONG" else "BUY"
        exit_resp = broker.place_market_order(active_sym, exchange, exit_action, qty, strategy="V1_Equity_Intraday_Engine")
        if exit_resp and exit_resp.get("status") == "success":
          last_ltp = state[active_sym]["last_quote"]["ltp"] if state[active_sym]["last_quote"] else entry_price
          exit_px = exit_resp["fill_price"] if exit_resp["fill_price"] > 0 else last_ltp
          if direction == "LONG":
            gross = round((exit_px - entry_price) * qty, 2)
          else:
            gross = round((entry_price - exit_px) * qty, 2)
          net = round(gross - charges_per_trade, 2)
          daily_pnl = round(daily_pnl + net, 2)
          trades_today += 1
          ts_str = now.strftime("%Y-%m-%d %H:%M:%S")
          log_trade([ts_str, active_sym, direction, qty, entry_price, exit_px, stop_loss, highest_stage, "EOD_SQUAREOFF", gross, net, daily_pnl])
          print(f"[EXIT EXECUTED] EOD MIS Square-off: {active_sym} @ ₹{exit_px:.2f} | Net P&L: ₹{net:.2f}")
          in_trade = False
          active_sym = None
          break

      # Hunting window closure check
      if not in_trade and now_t >= window_end:
        print(f"\n[WINDOW CLOSED] Past {window_end.strftime('%H:%M')} entry cutoff with no active position.")
        break

      # 6. Quote Polling & Depth Validation
      symbols_to_poll = [active_sym] if in_trade else watch_symbols
      quote_received = False

      for sym in symbols_to_poll:
        st = state[sym]
        q = broker.get_quote(sym, exchange)
        if q and q.get("ltp", 0) > 0:
          quote_received = True
          st["last_quote"] = q
          ltp = q["ltp"]
          st["ticks"].append(ltp)
          if st["candle_start_vol"] == 0:
            st["candle_start_vol"] = q.get("volume", 0.0)

          if in_trade and sym == active_sym:
            highest_price = max(highest_price, ltp)
            lowest_price = min(lowest_price, ltp)
            dist_sl = abs(ltp - stop_loss)
            print(
                f"  [{direction} {active_sym}] LTP: ₹{ltp:.2f} | SL: ₹{stop_loss:.2f} (Dist: ₹{dist_sl:.2f}) | Stage: {stage} | Trailing Peak: ₹{highest_price:.2f}   ",
                end="\r",
                flush=True,
            )
          elif not in_trade:
            print(
                f"  [HUNTING {direction}] {sym} LTP: ₹{ltp:.2f} | VWAP: ₹{st['session_vwap']:.2f} | Base High: ₹{st['base_high'] or 0:.2f} | Base Low: ₹{st['base_low'] or 0:.2f}   ",
                end="\r",
                flush=True,
            )

      if quote_received:
        consecutive_quote_failures = 0
      else:
        consecutive_quote_failures += 1
        if consecutive_quote_failures >= MAX_QUOTE_FAILURES:
          print(f"\n[CRITICAL FEED ALERT] {consecutive_quote_failures} consecutive quote failures!")
          if in_trade:
            print(f"[FAIL-SAFE EXIT] Attempting verified MARKET exit on {active_sym} due to dead feed...")
            exit_action = "SELL" if direction == "LONG" else "BUY"
            exit_resp = broker.place_market_order(active_sym, exchange, exit_action, qty, strategy="V1_Equity_Intraday_Engine")
            if exit_resp and exit_resp.get("status") == "success":
              last_ltp = state[active_sym]["last_quote"]["ltp"] if state[active_sym]["last_quote"] else entry_price
              exit_px = exit_resp["fill_price"] if exit_resp["fill_price"] > 0 else last_ltp
              if direction == "LONG":
                gross = round((exit_px - entry_price) * qty, 2)
              else:
                gross = round((entry_price - exit_px) * qty, 2)
              net = round(gross - charges_per_trade, 2)
              daily_pnl = round(daily_pnl + net, 2)
              trades_today += 1
              ts_str = now.strftime("%Y-%m-%d %H:%M:%S")
              log_trade([ts_str, active_sym, direction, qty, entry_price, exit_px, stop_loss, highest_stage, "FAILSAFE_DEAD_FEED", gross, net, daily_pnl])
              print(f"[EXIT EXECUTED] Dead-feed emergency exit confirmed: {active_sym} @ ₹{exit_px:.2f} | Net: ₹{net:.2f}")
              in_trade = False
              active_sym = None
              break
            else:
              print(f"[CRITICAL ERROR] Fail-safe exit order rejected or unreachable. Position remains active!")

      # 7. In-Trade Live Tick Trailing & Exit Evaluation
      if in_trade and state[active_sym]["last_quote"]:
        curr_ltp = state[active_sym]["last_quote"]["ltp"]
        exit_triggered = False
        exit_reason = None

        if direction == "LONG":
          # Stage 1: Breakeven Lock at +1.5R
          if curr_ltp >= stage1_trigger and stage == "ENTRY":
            stage = "STAGE_1"
            highest_stage = "STAGE_1"
            stop_loss = max(stop_loss, entry_price + cost_buffer_pts)
            print(f"\n[STAGE 1 HIT | {active_sym}] +1.5R achieved. Stop loss moved to cost-adjusted breakeven: ₹{stop_loss:.2f}")

          # Stage 2: Profit Lock (+1.0R) at +2.5R & Activate 2-Candle Swing / 9 EMA Trail
          if curr_ltp >= stage2_trigger and stage != "STAGE_2":
            stage = "STAGE_2"
            highest_stage = "STAGE_2"
            stop_loss = max(stop_loss, entry_price + risk_per_share)
            print(f"\n[STAGE 2 HIT | {active_sym}] +2.5R achieved. Locked +1.0R floor: ₹{stop_loss:.2f}. Swing trailing & 9 EMA active.")

          # Hard Target: 1:4.0 R:R
          if curr_ltp >= hard_target:
            exit_triggered = True
            exit_reason = "HARD_TARGET_4R"
            highest_stage = "HARD_TARGET_4R"

          # Stop Loss / Trailing Stop Trigger
          if curr_ltp <= stop_loss:
            exit_triggered = True
            if stage == "STAGE_2":
              exit_reason = "PROFIT_LOCK_1R"
            elif stage == "STAGE_1":
              exit_reason = "BREAKEVEN_STOP"
            else:
              exit_reason = "STOP_LOSS"

        elif direction == "SHORT":
          # Stage 1: Breakeven Lock at +1.5R (Price drops)
          if curr_ltp <= stage1_trigger and stage == "ENTRY":
            stage = "STAGE_1"
            highest_stage = "STAGE_1"
            stop_loss = min(stop_loss, entry_price - cost_buffer_pts)
            print(f"\n[STAGE 1 HIT | {active_sym}] +1.5R achieved. Stop loss moved to cost-adjusted breakeven: ₹{stop_loss:.2f}")

          # Stage 2: Profit Lock (+1.0R) at +2.5R & Activate 2-Candle Swing / 9 EMA Trail
          if curr_ltp <= stage2_trigger and stage != "STAGE_2":
            stage = "STAGE_2"
            highest_stage = "STAGE_2"
            stop_loss = min(stop_loss, entry_price - risk_per_share)
            print(f"\n[STAGE 2 HIT | {active_sym}] +2.5R achieved. Locked +1.0R floor: ₹{stop_loss:.2f}. Swing trailing & 9 EMA active.")

          # Hard Target: 1:4.0 R:R
          if curr_ltp <= hard_target:
            exit_triggered = True
            exit_reason = "HARD_TARGET_4R"
            highest_stage = "HARD_TARGET_4R"

          # Stop Loss / Trailing Stop Trigger
          if curr_ltp >= stop_loss:
            exit_triggered = True
            if stage == "STAGE_2":
              exit_reason = "PROFIT_LOCK_1R"
            elif stage == "STAGE_1":
              exit_reason = "BREAKEVEN_STOP"
            else:
              exit_reason = "STOP_LOSS"

        if exit_triggered:
          exit_action = "SELL" if direction == "LONG" else "BUY"
          print(f"\n[TRIGGER: {exit_reason}] Executing {exit_action} {qty} {active_sym} @ Market (LTP: ₹{curr_ltp:.2f})...")
          exit_resp = broker.place_market_order(active_sym, exchange, exit_action, qty, strategy="V1_Equity_Intraday_Engine")
          if exit_resp and exit_resp.get("status") == "success":
            exit_px = exit_resp["fill_price"] if exit_resp["fill_price"] > 0 else curr_ltp
            if direction == "LONG":
              gross = round((exit_px - entry_price) * qty, 2)
            else:
              gross = round((entry_price - exit_px) * qty, 2)
            net = round(gross - charges_per_trade, 2)
            daily_pnl = round(daily_pnl + net, 2)
            trades_today += 1
            ts_str = now.strftime("%Y-%m-%d %H:%M:%S")
            log_trade([ts_str, active_sym, direction, qty, entry_price, exit_px, stop_loss, highest_stage, exit_reason, gross, net, daily_pnl])
            print(f"[EXIT CONFIRMED] {active_sym} exited @ ₹{exit_px:.2f} | Gross: ₹{gross:.2f} | Net: ₹{net:.2f} | Daily: ₹{daily_pnl:.2f}")
            in_trade = False
            active_sym = None
            if config.MODE == "SIMULATION" or trades_today >= max_trades or daily_pnl <= max_daily_loss:
              break
            continue

      # 8. 3-Minute Wall-Clock Candle Completion State Machine
      curr_bucket = current_candle_bucket()
      candle_closed = False

      if config.MODE == "SIMULATION":
        sim_ticks_in_bucket += 1
        if sim_ticks_in_bucket >= 4:
          candle_closed = True
          sim_ticks_in_bucket = 0
      else:
        if curr_bucket != last_bucket:
          last_bucket = curr_bucket
          if discard_first_partial_bucket:
            discard_first_partial_bucket = False
            for s in watch_symbols:
              state[s]["ticks"] = []
            print(f"\n[CANDLE SYNC] First truncated startup bucket discarded. Clean 3m aggregation engaged.")
            continue
          candle_closed = True

      if candle_closed:
        for sym in symbols_to_poll:
          st = state[sym]
          if not st["ticks"]:
            continue

          c_open = st["ticks"][0]
          c_close = st["ticks"][-1]
          c_high = max(st["ticks"])
          c_low = min(st["ticks"])
          st["ticks"] = []

          # Compute candle volume
          cur_vol = st["last_quote"].get("volume", 0.0) if st["last_quote"] else 0.0
          if config.MODE == "SIMULATION" and not in_trade:
            c_volume = 75000.0
          else:
            c_volume = max(100.0, float(cur_vol - st["candle_start_vol"])) if cur_vol > st["candle_start_vol"] else 30000.0
          st["candle_start_vol"] = cur_vol

          new_candle = {
              "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
              "open": c_open,
              "high": c_high,
              "low": c_low,
              "close": c_close,
              "volume": c_volume,
          }
          st["candles"].append(new_candle)

          # Update cumulative intraday Session VWAP
          typ_px = (c_high + c_low + c_close) / 3.0
          st["sum_pv"] += typ_px * c_volume
          st["sum_vol"] += c_volume
          if st["sum_vol"] > 0:
            st["session_vwap"] = round(st["sum_pv"] / st["sum_vol"], 2)

          # Freeze-Box tracking (configurable via EQUITY_OBSERVE_START - EQUITY_WINDOW_START)
          if observe_start <= now_t < window_start:
            st["base_high"] = c_high if st["base_high"] is None else max(st["base_high"], c_high)
            st["base_low"] = c_low if st["base_low"] is None else min(st["base_low"], c_low)
            print(
                f"\n[CANDLE CLOSE | {sym}] 3m: O:{c_open:.2f} H:{c_high:.2f} L:{c_low:.2f} C:{c_close:.2f} (Vol: {int(c_volume)})"
                f" | Freeze Box: [{st['base_low']:.2f} - {st['base_high']:.2f}] | VWAP: ₹{st['session_vwap']:.2f}"
            )

          # In-Trade Stage 2 Trailing stop adjustments (Swing low/high & 9 EMA)
          if in_trade and sym == active_sym and stage == "STAGE_2":
            closes = [c["close"] for c in st["candles"]]
            ema9 = compute_ema(closes, period=9)

            if direction == "LONG":
              if len(st["candles"]) >= 2:
                swing_low = min(st["candles"][-1]["low"], st["candles"][-2]["low"])
                if swing_low > stop_loss:
                  stop_loss = round(swing_low, 2)
                  print(f"\n[SWING TRAIL | {sym}] Trailing SL tightened to 2-candle low: ₹{stop_loss:.2f}")

              if c_close < ema9:
                print(f"\n[9 EMA EXIT] Candle close ₹{c_close:.2f} broke below 9 EMA ₹{ema9:.2f}. Executing exit...")
                exit_resp = broker.place_market_order(active_sym, exchange, "SELL", qty, strategy="V1_Equity_Intraday_Engine")
                if exit_resp and exit_resp.get("status") == "success":
                  exit_px = exit_resp["fill_price"] if exit_resp["fill_price"] > 0 else c_close
                  gross = round((exit_px - entry_price) * qty, 2)
                  net = round(gross - charges_per_trade, 2)
                  daily_pnl = round(daily_pnl + net, 2)
                  trades_today += 1
                  ts_str = now.strftime("%Y-%m-%d %H:%M:%S")
                  log_trade([ts_str, active_sym, direction, qty, entry_price, exit_px, stop_loss, "STAGE_2", "9EMA_BREAK", gross, net, daily_pnl])
                  print(f"[EXIT CONFIRMED] 9 EMA break exit: {active_sym} @ ₹{exit_px:.2f} | Net: ₹{net:.2f}")
                  in_trade = False
                  active_sym = None
                  if trades_today >= max_trades or daily_pnl <= max_daily_loss:
                    break
                  continue

            elif direction == "SHORT":
              if len(st["candles"]) >= 2:
                swing_high = max(st["candles"][-1]["high"], st["candles"][-2]["high"])
                if swing_high < stop_loss:
                  stop_loss = round(swing_high, 2)
                  print(f"\n[SWING TRAIL | {sym}] Trailing SL tightened to 2-candle high: ₹{stop_loss:.2f}")

              if c_close > ema9:
                print(f"\n[9 EMA EXIT] Candle close ₹{c_close:.2f} broke above 9 EMA ₹{ema9:.2f}. Executing exit...")
                exit_resp = broker.place_market_order(active_sym, exchange, "BUY", qty, strategy="V1_Equity_Intraday_Engine")
                if exit_resp and exit_resp.get("status") == "success":
                  exit_px = exit_resp["fill_price"] if exit_resp["fill_price"] > 0 else c_close
                  gross = round((entry_price - exit_px) * qty, 2)
                  net = round(gross - charges_per_trade, 2)
                  daily_pnl = round(daily_pnl + net, 2)
                  trades_today += 1
                  ts_str = now.strftime("%Y-%m-%d %H:%M:%S")
                  log_trade([ts_str, active_sym, direction, qty, entry_price, exit_px, stop_loss, "STAGE_2", "9EMA_BREAK", gross, net, daily_pnl])
                  print(f"[EXIT CONFIRMED] 9 EMA break exit: {active_sym} @ ₹{exit_px:.2f} | Net: ₹{net:.2f}")
                  in_trade = False
                  active_sym = None
                  if trades_today >= max_trades or daily_pnl <= max_daily_loss:
                    break
                  continue

          # Hunting Window Entry Signals (configurable via EQUITY_WINDOW_START - EQUITY_WINDOW_END)
          if not in_trade and window_start <= now_t < window_end:
            if st["base_high"] is None or st["base_low"] is None:
              continue

            q = st["last_quote"]
            if not q or not q.get("valid_depth", False):
              continue

            spread_pct = (q["spread"] / q["ltp"]) * 100.0 if q["ltp"] > 0 else 999.0
            if spread_pct > MAX_SPREAD_PCT:
              continue

            vol_surge = check_volume_surge(st["candles"][:-1], c_volume)

            # LONG Entry Evaluation
            if direction == "LONG":
              if (
                  c_close > st["base_high"]
                  and c_close > st["session_vwap"]
                  and c_close <= (st["base_high"] * CHASE_GUARD_LONG)
                  and vol_surge
              ):
                print(f"\n[LONG SIGNAL DETECTED | {sym}] Breakout above Base High ₹{st['base_high']:.2f} & VWAP ₹{st['session_vwap']:.2f}")
                print(f"  Close: ₹{c_close:.2f} | Vol Surge: {vol_surge} (Candle Vol: {int(c_volume)}) | Spread: {spread_pct:.4f}%")

                entry_action = "BUY"
                pre_sl = max(st["base_low"], c_close * (1.0 - MAX_STRUCTURAL_STOP_PCT))
                pre_risk_share = max(0.50, c_close - pre_sl)
                raw_q = int(max_risk_trade // pre_risk_share)
                notional_q = int(max_notional // c_close)
                trade_qty = max(1, min(raw_q, notional_q))

                print(f"  Sizing: Qty={trade_qty} | Notional=₹{trade_qty * c_close:.2f} | Planned Risk=₹{trade_qty * pre_risk_share:.2f}")
                order_resp = broker.place_market_order(sym, exchange, entry_action, trade_qty, strategy="V1_Equity_Intraday_Engine")

                if order_resp and order_resp.get("status") == "success":
                  in_trade = True
                  active_sym = sym
                  qty = trade_qty
                  entry_price = order_resp["fill_price"] if order_resp["fill_price"] > 0 else c_close
                  initial_sl = max(st["base_low"], entry_price * (1.0 - MAX_STRUCTURAL_STOP_PCT))
                  stop_loss = initial_sl
                  risk_per_share = max(0.50, entry_price - stop_loss)
                  stage = "ENTRY"
                  highest_stage = "ENTRY"
                  highest_price = entry_price
                  stage1_trigger = round(entry_price + (1.5 * risk_per_share), 2)
                  stage2_trigger = round(entry_price + (2.5 * risk_per_share), 2)
                  hard_target = round(entry_price + (4.0 * risk_per_share), 2)
                  cost_buffer_pts = round((charges_per_trade / qty) + 0.05, 2)

                  print(f"[ENTRY CONFIRMED] LONG {qty} {sym} @ ₹{entry_price:.2f}")
                  print(f"  SL: ₹{stop_loss:.2f} (Risk: ₹{risk_per_share:.2f}/sh) | Stage 1 (+1.5R): ₹{stage1_trigger:.2f} | Stage 2 (+2.5R): ₹{stage2_trigger:.2f} | 4R Target: ₹{hard_target:.2f}")
                  break

            # SHORT Entry Evaluation
            elif direction == "SHORT":
              if (
                  c_close < st["base_low"]
                  and c_close < st["session_vwap"]
                  and c_close >= (st["base_low"] * CHASE_GUARD_SHORT)
                  and vol_surge
              ):
                print(f"\n[SHORT SIGNAL DETECTED | {sym}] Breakdown below Base Low ₹{st['base_low']:.2f} & VWAP ₹{st['session_vwap']:.2f}")
                print(f"  Close: ₹{c_close:.2f} | Vol Surge: {vol_surge} (Candle Vol: {int(c_volume)}) | Spread: {spread_pct:.4f}%")

                entry_action = "SELL"
                pre_sl = min(st["base_high"], c_close * (1.0 + MAX_STRUCTURAL_STOP_PCT))
                pre_risk_share = max(0.50, pre_sl - c_close)
                raw_q = int(max_risk_trade // pre_risk_share)
                notional_q = int(max_notional // c_close)
                trade_qty = max(1, min(raw_q, notional_q))

                print(f"  Sizing: Qty={trade_qty} | Notional=₹{trade_qty * c_close:.2f} | Planned Risk=₹{trade_qty * pre_risk_share:.2f}")
                order_resp = broker.place_market_order(sym, exchange, entry_action, trade_qty, strategy="V1_Equity_Intraday_Engine")

                if order_resp and order_resp.get("status") == "success":
                  in_trade = True
                  active_sym = sym
                  qty = trade_qty
                  entry_price = order_resp["fill_price"] if order_resp["fill_price"] > 0 else c_close
                  initial_sl = min(st["base_high"], entry_price * (1.0 + MAX_STRUCTURAL_STOP_PCT))
                  stop_loss = initial_sl
                  risk_per_share = max(0.50, stop_loss - entry_price)
                  stage = "ENTRY"
                  highest_stage = "ENTRY"
                  lowest_price = entry_price
                  stage1_trigger = round(entry_price - (1.5 * risk_per_share), 2)
                  stage2_trigger = round(entry_price - (2.5 * risk_per_share), 2)
                  hard_target = round(entry_price - (4.0 * risk_per_share), 2)
                  cost_buffer_pts = round((charges_per_trade / qty) + 0.05, 2)

                  print(f"[ENTRY CONFIRMED] SHORT {qty} {sym} @ ₹{entry_price:.2f}")
                  print(f"  SL: ₹{stop_loss:.2f} (Risk: ₹{risk_per_share:.2f}/sh) | Stage 1 (+1.5R): ₹{stage1_trigger:.2f} | Stage 2 (+2.5R): ₹{stage2_trigger:.2f} | 4R Target: ₹{hard_target:.2f}")
                  break

      time.sleep(0.05 if config.MODE == "SIMULATION" else 1.5)

  except KeyboardInterrupt:
    print("\n[USER INTERRUPT] Stopping Equity Engine safely...")
    if in_trade:
      print(f"[CRITICAL WARNING] Active position open in {active_sym} ({direction} {qty} shares).")
      ans = input("Square-off active position now at Market? [y/N]: ").strip().lower()
      if ans == "y":
        exit_action = "SELL" if direction == "LONG" else "BUY"
        broker.place_market_order(active_sym, exchange, exit_action, qty, strategy="V1_Equity_Intraday_Engine")
        print("[EMERGENCY EXIT] Sent square-off order to broker.")
  finally:
    broker.shutdown()
    print(f"\n[ENGINE TERMINATED] Daily realized P&L: ₹{daily_pnl:.2f} ({trades_today}/{max_trades} trades executed).")


if __name__ == "__main__":
  is_headless = "--headless" in sys.argv or "--sim" in sys.argv or os.getenv("HEADLESS") == "1"
  run_equity_engine(headless=is_headless)