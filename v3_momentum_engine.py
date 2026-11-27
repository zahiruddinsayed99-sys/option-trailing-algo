import csv
import datetime
import os
import sys
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
MAX_QUOTE_FAILURES = 10      # Circuit breaker threshold (~20-30s dead feed)


def _parse_hhmm(hhmm_str, default_time):
  """Safely parses 'HH:MM' config strings into datetime.time objects."""
  try:
    h, m = map(int, str(hhmm_str).strip().split(":"))
    return datetime.time(h, m)
  except Exception:
    return default_time


def _is_today_candle(ts_str, today_str):
  """Returns True if candle timestamp belongs to today's trading session."""
  s = str(ts_str or "").strip()
  if not s:
    return False
  if s.startswith(today_str):
    return True
  try:
    today_dmy = datetime.datetime.strptime(today_str, "%Y-%m-%d").strftime("%d-%m-%Y")
    if s.startswith(today_dmy):
      return True
  except Exception:
    pass
  return False


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
  """Computes Exponential Moving Average over a sequence of close prices."""
  if not closes:
    return 0.0
  k = 2.0 / (period + 1)
  ema = closes[0]
  for c in closes[1:]:
    ema = (c * k) + (ema * (1.0 - k))
  return ema


def compute_sma(values, period=20):
  """Computes Simple Moving Average over the trailing `period` observations."""
  if not values:
    return 0.0
  window = values[-period:]
  return sum(window) / len(window)


def current_candle_bucket():
  now = datetime.datetime.now()
  return (now.hour * 3600 + now.minute * 60 + now.second) // CANDLE_SEC


def sync_strike_indicators(broker, state, sym, exchange):
  """Hydrates prior-day + current-day 3m candles for instant VWAP, EMA 9/21, and Vol SMA20."""
  st = state[sym]
  if st.get("hydrated"):
    return

  t0 = time.perf_counter()
  hist_candles = broker.fetch_multi_day_history(sym, exchange, interval="3m", lookback_days=4)
  today_str = datetime.date.today().strftime("%Y-%m-%d")

  # Drop an in-progress live bucket candle from REST history so it is not double-counted
  if config.MODE != "SIMULATION" and hist_candles:
    last_ts = str(hist_candles[-1].get("timestamp", ""))
    if _is_today_candle(last_ts, today_str):
      try:
        t_part = last_ts.split(" ")[1][:5] if " " in last_ts else last_ts[:5]
        c_t = _parse_hhmm(t_part, None)
        if c_t is not None:
          c_bucket = (c_t.hour * 3600 + c_t.minute * 60) // CANDLE_SEC
          if c_bucket == current_candle_bucket():
            hist_candles = hist_candles[:-1]
      except Exception:
        pass

  sum_pv = 0.0
  sum_vol = 0.0
  for c in hist_candles:
    if _is_today_candle(c.get("timestamp", ""), today_str):
      vol = float(c.get("volume", 0.0) or 0.0)
      typ_px = (c["high"] + c["low"] + c["close"]) / 3.0
      sum_pv += typ_px * vol
      sum_vol += vol

  st["candles"] = list(hist_candles)
  st["sum_pv"] = sum_pv
  st["sum_vol"] = sum_vol
  if sum_vol > 0:
    st["session_vwap"] = round(sum_pv / sum_vol, 2)
  elif hist_candles:
    st["session_vwap"] = round(hist_candles[-1]["close"], 2)
  else:
    st["session_vwap"] = 0.0
  st["hydrated"] = True

  elapsed = time.perf_counter() - t0
  closes = [c["close"] for c in st["candles"]]
  ema9 = compute_ema(closes, period=9)
  ema21 = compute_ema(closes, period=21)
  vol_sma20 = compute_sma([c.get("volume", 0.0) for c in st["candles"]], period=20)
  print(
      f"\n[HYDRATED | {sym}] {len(hist_candles)} 3m candles in {elapsed:.2f}s"
      f" | VWAP: ₹{st['session_vwap']:.2f} | 9 EMA: ₹{ema9:.2f}"
      f" | 21 EMA: ₹{ema21:.2f} | Vol SMA20: {int(vol_sma20)}"
  )


def _execute_exit(
    broker,
    active_sym,
    exchange,
    qty,
    entry_price,
    highest_price,
    stage,
    exit_reason,
    fallback_px,
    charges_per_trade,
    daily_pnl,
    trades_today,
    now,
):
  """Places exit order, logs atomic trade record, and returns (success, new_daily_pnl, new_trades_today)."""
  exit_resp = broker.place_market_order(active_sym, exchange, "SELL", qty)
  if not exit_resp or exit_resp.get("status") != "success":
    return False, daily_pnl, trades_today

  exit_px = exit_resp["fill_price"] if exit_resp["fill_price"] > 0 else fallback_px
  gross = round((exit_px - entry_price) * qty, 2)
  net = round(gross - charges_per_trade, 2)
  new_daily_pnl = round(daily_pnl + net, 2)
  new_trades_today = trades_today + 1
  print(
      f"\n[EXIT EXECUTED] {active_sym} @ ₹{exit_px:.2f} | Reason: {exit_reason}"
      f" | Net P&L: ₹{net:.2f} | Daily P&L: ₹{new_daily_pnl:.2f} | Trades: {new_trades_today}"
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
      new_daily_pnl,
  ])
  return True, new_daily_pnl, new_trades_today


def run_v3_engine(auto_mode=False):
  daily_pnl, trades_today = init_csv()
  broker = BrokerAdapter()

  default_list = getattr(config, "CANDIDATE_STRIKES", [config.SYMBOL])
  default_str = ",".join(default_list)
  is_auto = auto_mode or ("--auto" in sys.argv) or ("--sim" in sys.argv) or getattr(config, "AUTO_START", False)

  print("\n=== V4.0 CONFLUENCE MULTI-STRIKE MOMENTUM ENGINE SETUP ===")
  if is_auto:
    strikes = list(default_list)
    exchange = config.EXCHANGE
    qty = int(config.QTY)
    print(f"[AUTO MODE] Strikes: {strikes} | Exchange: {exchange} | Qty: {qty}")
  else:
    sym_in = input(f"Candidate Strikes [{default_str}]: ").strip().upper()
    strikes = [s.strip() for s in sym_in.split(",") if s.strip()] if sym_in else list(default_list)

    exch_in = input(f"Exchange [{config.EXCHANGE}]: ").strip().upper()
    exchange = exch_in if exch_in else config.EXCHANGE

    qty_in = input(f"Quantity [{config.QTY}]: ").strip()
    qty = int(qty_in) if qty_in else int(config.QTY)

  # Dynamic capital-normalized premium band & percentage-based SL / confluence guardrails
  min_cap = getattr(config, "MIN_CAPITAL_PER_LOT", 4000.0)
  max_cap = getattr(config, "MAX_CAPITAL_PER_LOT", 5500.0)
  min_prem = round(min_cap / qty, 2)
  max_prem = round(max_cap / qty, 2)
  max_sl_pct = getattr(config, "MAX_SL_PCT", 0.25)
  max_ema_ext_pct = getattr(config, "MAX_EMA_EXTENSION_PCT", 0.08)
  vol_surge_mult = getattr(config, "VOLUME_SURGE_MULT", 1.3)
  charges_per_trade = getattr(config, "ESTIMATED_CHARGES_PER_TRADE", 55.0)

  # Configurable Session Time Windows (IST)
  if config.MODE == "SIMULATION":
    observe_start = datetime.time(0, 0)
    window_start = datetime.time(0, 0)
    window_end = datetime.time(23, 59)
    eod_exit_time = datetime.time(23, 59)
  else:
    observe_start = _parse_hhmm(getattr(config, "OPTIONS_OBSERVE_START", "09:15"), datetime.time(9, 15))
    window_start = _parse_hhmm(getattr(config, "OPTIONS_WINDOW_START", "09:30"), datetime.time(9, 30))
    window_end = _parse_hhmm(getattr(config, "OPTIONS_WINDOW_END", "13:30"), datetime.time(13, 30))
    eod_exit_time = _parse_hhmm(getattr(config, "OPTIONS_EOD_EXIT", "15:15"), datetime.time(15, 15))

  state = {
      s: {
          "ticks": [],
          "candles": [],
          "sum_pv": 0.0,
          "sum_vol": 0.0,
          "session_vwap": 0.0,
          "candle_start_vol": None,
          "hydrated": False,
          "last_quote": None,
      }
      for s in strikes
  }

  # Upfront 4-strike WebSocket subscription + instant historical indicator hydration
  broker.subscribe_batch(strikes, exchange)
  active_idx = 0
  active_sym = strikes[active_idx]
  sync_strike_indicators(broker, state, active_sym, exchange)

  in_trade = False
  entry_price = 0.0
  initial_risk_pts = 0.0
  breakeven_trigger = 0.0
  stage2_r_trigger = 0.0
  stage2_pct_trigger = 0.0
  locked_floor = 0.0
  highest_price = 0.0
  stop_loss = 0.0
  stage = "IDLE"
  climax_armed = False
  climax_trigger_price = None

  consecutive_quote_failures = 0
  last_rotation_check_ts = 0.0
  max_trades = getattr(config, "MAX_TRADES_PER_DAY", 3)
  max_daily_loss = getattr(config, "OPTIONS_DAILY_MAX_LOSS", getattr(config, "MAX_DAILY_LOSS", -1200.0))

  last_bucket = current_candle_bucket()
  discard_first_partial_bucket = config.MODE != "SIMULATION"
  sim_ticks_in_bucket = 0

  print(
      f"\n>>> Starting V4.0 Confluence Engine [{config.MODE}] | {len(strikes)} Strikes Subscribed"
      f" | Observe [{observe_start.strftime('%H:%M')}]"
      f" | Trade [{window_start.strftime('%H:%M')}-{window_end.strftime('%H:%M')}]"
      f" | Band (₹{min_cap:.0f}-₹{max_cap:.0f}/lot): ₹{min_prem:.2f}-₹{max_prem:.2f}"
      f" | Max SL: {int(max_sl_pct*100)}% | Max Ext: {int(max_ema_ext_pct*100)}% | Vol: {vol_surge_mult}x"
      f" | Daily Loss Cap: ₹{max_daily_loss:.0f}"
      f" | Resume: {trades_today}/{max_trades} trades (₹{daily_pnl:.2f}) <<<"
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

      # 2. Hunting Window Cutoff Check
      if not in_trade and now_t >= window_end:
        print(f"\n[WINDOW CLOSED] Past {window_end.strftime('%H:%M')} entry cutoff with no open position.")
        break

      # Simulation completion check
      if config.MODE == "SIMULATION" and broker.sim_step >= len(broker.sim_prices):
        if not in_trade:
          print("\n[SIMULATION COMPLETE] All synthetic price ticks processed cleanly.")
          break
        elif broker.sim_step >= len(broker.sim_prices) + 8:
          last_ltp = state[active_sym]["last_quote"]["ltp"] if state[active_sym]["last_quote"] else entry_price
          ok, daily_pnl, trades_today = _execute_exit(
              broker, active_sym, exchange, qty, entry_price, highest_price,
              stage, "SIM_END_SQUAREOFF", last_ltp, charges_per_trade,
              daily_pnl, trades_today, now,
          )
          in_trade = False
          print("\n[SIMULATION COMPLETE] Closed open simulated trade at series end.")
          break

      # 3. Poll active strike (WebSocket primary + REST fallback + Verified Failsafe Exit)
      q = broker.get_quote(active_sym, exchange)
      if q and q.get("ltp", 0) > 0:
        consecutive_quote_failures = 0
        st_active = state[active_sym]
        st_active["last_quote"] = q
        st_active["ticks"].append(q["ltp"])
        cur_vol = float(q.get("volume", 0.0) or 0.0)
        if st_active["candle_start_vol"] is None:
          st_active["candle_start_vol"] = cur_vol
        if not in_trade and now_t < window_start:
          sp_txt = f"₹{q['spread']:.2f}" if q.get("valid_depth", True) else "NO_DEPTH"
          print(
              f"  [LIVE TICK] {active_sym} LTP: ₹{q['ltp']:.2f} | VWAP: ₹{st_active['session_vwap']:.2f} | Spread: {sp_txt}   ",
              end="\r",
              flush=True,
          )
      else:
        consecutive_quote_failures += 1
        if consecutive_quote_failures >= MAX_QUOTE_FAILURES:
          print(f"\n[CRITICAL FEED ALERT] {consecutive_quote_failures} consecutive quote failures on {active_sym}!")
          if in_trade:
            print("[FAIL-SAFE EXIT] Attempting immediate MARKET exit due to broken data feed...")
            last_ltp = (
                state[active_sym]["last_quote"]["ltp"]
                if state[active_sym]["last_quote"]
                else entry_price
            )
            ok, daily_pnl, trades_today = _execute_exit(
                broker,
                active_sym,
                exchange,
                qty,
                entry_price,
                highest_price,
                stage,
                "FEED_FAILURE_FAILSAFE",
                last_ltp,
                charges_per_trade,
                daily_pnl,
                trades_today,
                now,
            )
            if ok:
              in_trade = False
              stage = "IDLE"
              locked_floor = 0.0
              climax_armed = False
              climax_trigger_price = None
            else:
              print(
                  f"[FATAL ORDER ALERT] Failsafe SELL failed for {active_sym}!"
                  " Position STILL OPEN at broker — keeping in_trade=True and retrying!"
              )
          consecutive_quote_failures = 0
        time.sleep(2.0)
        continue

      # 4. Dynamic OTM Strike Auto-Rotation (Zero REST / Zero 429 via upfront WS subscription)
      if (
          not in_trade
          and len(strikes) > 1
          and state[active_sym]["last_quote"]
          and (time.time() - last_rotation_check_ts) >= 15.0
      ):
        curr_ltp = state[active_sym]["last_quote"]["ltp"]
        allow_rot_rest = not broker.ws_connected
        if curr_ltp > max_prem and active_idx + 1 < len(strikes):
          last_rotation_check_ts = time.time()
          for next_i in range(active_idx + 1, len(strikes)):
            cand_s = strikes[next_i]
            cand_q = broker.get_quote(cand_s, exchange, advance_sim=False, allow_rest=allow_rot_rest)
            state[cand_s]["last_quote"] = cand_q
            if (
                cand_q
                and cand_q.get("valid_depth", False)
                and cand_q["ltp"] > 0
                and cand_q["ltp"] <= max_prem
                and cand_q["spread"] <= round(cand_q["ltp"] * 0.005, 4)
            ):
              print(
                  f"\n>>> [OTM ROTATE UP] {active_sym} LTP ₹{curr_ltp:.2f} > ₹{max_prem:.2f}."
                  f" Switching to {cand_s} @ ₹{cand_q['ltp']:.2f} <<<"
              )
              state[active_sym]["ticks"].clear()
              state[active_sym]["hydrated"] = False
              active_idx = next_i
              active_sym = cand_s
              sync_strike_indicators(broker, state, active_sym, exchange)
              state[active_sym]["candle_start_vol"] = float(cand_q.get("volume", 0.0) or 0.0)
              break
        elif curr_ltp < min_prem and active_idx - 1 >= 0:
          last_rotation_check_ts = time.time()
          for prev_i in range(active_idx - 1, -1, -1):
            cand_s = strikes[prev_i]
            cand_q = broker.get_quote(cand_s, exchange, advance_sim=False, allow_rest=allow_rot_rest)
            state[cand_s]["last_quote"] = cand_q
            if (
                cand_q
                and cand_q.get("valid_depth", False)
                and min_prem <= cand_q["ltp"] <= max_prem
                and cand_q["spread"] <= round(cand_q["ltp"] * 0.005, 4)
            ):
              print(
                  f"\n>>> [OTM ROTATE DOWN] {active_sym} LTP ₹{curr_ltp:.2f} < ₹{min_prem:.2f}."
                  f" Switching back to {cand_s} @ ₹{cand_q['ltp']:.2f} <<<"
              )
              state[active_sym]["ticks"].clear()
              state[active_sym]["hydrated"] = False
              active_idx = prev_i
              active_sym = cand_s
              sync_strike_indicators(broker, state, active_sym, exchange)
              state[active_sym]["candle_start_vol"] = float(cand_q.get("volume", 0.0) or 0.0)
              break

      # 5. Intra-Candle Tick Exit Management
      if in_trade and state[active_sym]["last_quote"]:
        ltp = state[active_sym]["last_quote"]["ltp"]
        if ltp > highest_price:
          highest_price = ltp

        # Stage 1 (>= 1.5R profit): Move SL to cost-adjusted Breakeven (entry_price + 0.30)
        if stage == "INITIAL_SL" and ltp >= breakeven_trigger:
          be_sl = round(entry_price + 0.30, 2)
          stop_loss = max(stop_loss, be_sl)
          stage = "STAGE1_1.5R_BREAKEVEN"
          print(
              f"\n[STAGE 1: 1.5R BREAKEVEN] {active_sym} hit ₹{ltp:.2f} (>= ₹{breakeven_trigger:.2f})."
              f" SL moved to Breakeven: ₹{stop_loss:.2f}"
          )

        # Stage 2 (>= +50% premium gain OR >= 2.0R profit): Lock minimum +25% floor & activate candle trail
        pct25_floor = round(entry_price * 1.25, 2)
        if stage != "STAGE2_PROFIT_TRAIL" and (ltp >= stage2_pct_trigger or ltp >= stage2_r_trigger):
          # Guard against setting SL above LTP when 2.0R < +25% (tight structural SL)
          locked_floor = pct25_floor if ltp >= pct25_floor + 0.50 else round(entry_price + initial_risk_pts, 2)
          stop_loss = max(stop_loss, locked_floor)
          stage = "STAGE2_PROFIT_TRAIL"
          print(
              f"\n[STAGE 2: PROFIT TRAIL ACTIVE] {active_sym} hit ₹{ltp:.2f}."
              f" Floor SL locked at ₹{stop_loss:.2f}"
          )
        elif stage == "STAGE2_PROFIT_TRAIL" and locked_floor < pct25_floor and (ltp >= stage2_pct_trigger or ltp >= pct25_floor + 0.50):
          locked_floor = pct25_floor
          stop_loss = max(stop_loss, locked_floor)
          print(f"\n[STAGE 2: +25% FLOOR LOCKED] {active_sym} hit ₹{ltp:.2f}. Floor raised to ₹{locked_floor:.2f}")

        exit_reason = None
        if ltp <= stop_loss:
          exit_reason = f"STOP_LOSS ({stage})"
        elif ltp >= entry_price * 2.00:
          exit_reason = "TARGET_2X_DOUBLED"
        elif now_t >= eod_exit_time:
          exit_reason = "EOD_SQUARE_OFF"

        if exit_reason:
          ok, daily_pnl, trades_today = _execute_exit(
              broker,
              active_sym,
              exchange,
              qty,
              entry_price,
              highest_price,
              stage,
              exit_reason,
              ltp,
              charges_per_trade,
              daily_pnl,
              trades_today,
              now,
          )
          if ok:
            in_trade = False
            stage = "IDLE"
            locked_floor = 0.0
            climax_armed = False
            climax_trigger_price = None
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
          if st["last_quote"]:
            st["candle_start_vol"] = float(st["last_quote"].get("volume", 0.0) or 0.0)
          print("\n[SYNC] Discarded truncated startup candle; aligned to clean 3-minute boundary.")
          continue

        c_open = st["ticks"][0]
        c_high = max(st["ticks"])
        c_low = min(st["ticks"])
        c_close = st["ticks"][-1]
        st["ticks"].clear()

        cur_vol = float(st["last_quote"].get("volume", 0.0) or 0.0) if st["last_quote"] else 0.0
        start_vol = st["candle_start_vol"] if st["candle_start_vol"] is not None else cur_vol
        c_volume = max(0.0, cur_vol - start_vol) if cur_vol >= start_vol else 0.0
        if cur_vol > 0:
          st["candle_start_vol"] = cur_vol

        # Ignore pre-observe_start opening bell ticks
        if now_t < observe_start:
          continue

        candle = {
            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
            "open": c_open,
            "high": c_high,
            "low": c_low,
            "close": c_close,
            "volume": c_volume,
        }
        prior_candles = list(st["candles"])
        st["candles"].append(candle)

        # Incrementally update Session VWAP on every closed 3m candle
        if c_volume > 0:
          typ_px = (c_high + c_low + c_close) / 3.0
          st["sum_pv"] += typ_px * c_volume
          st["sum_vol"] += c_volume
        if st["sum_vol"] > 0:
          st["session_vwap"] = round(st["sum_pv"] / st["sum_vol"], 2)
        elif st["session_vwap"] <= 0:
          st["session_vwap"] = round(c_close, 2)

        closes = [c["close"] for c in st["candles"]]
        ema9 = compute_ema(closes, period=9)
        ema21 = compute_ema(closes, period=21)
        vol_sma20 = compute_sma([c.get("volume", 0.0) for c in prior_candles], period=20)
        session_vwap = st["session_vwap"]

        # PHASE A: Pre-Window Observation (e.g. 09:15 - 09:30)
        if now_t < window_start:
          print(
              f"\n[PRE-WINDOW 3M | {active_sym}] Close: {c_close:.2f} | VWAP: {session_vwap:.2f}"
              f" | 9EMA: {ema9:.2f} | 21EMA: {ema21:.2f} | Vol: {int(c_volume)} / SMA20: {int(vol_sma20)}"
          )

        # PHASE B: VWAP + 9/21 EMA + Volume Confluence Entry Hunting
        elif not in_trade:
          q_now = st["last_quote"]
          valid_depth = bool(q_now and q_now.get("valid_depth", False))
          ltp_now = q_now["ltp"] if q_now else c_close
          spread_now = q_now["spread"] if q_now else 999.0
          spread_pct = (spread_now / ltp_now) * 100.0 if ltp_now > 0 else 999.0
          ext_pct = ((c_close - ema9) / ema9) * 100.0 if ema9 > 0 else 0.0
          vol_ratio = (c_volume / vol_sma20) if vol_sma20 > 0 else 0.0

          sp_disp = f"{spread_pct:.2f}%" if valid_depth else "NO_DEPTH"
          print(
              f"[SCANNING 3M | {active_sym}] C:{c_close:.2f} | VWAP:{session_vwap:.2f}"
              f" | 9E:{ema9:.2f} | 21E:{ema21:.2f} | Ext:{ext_pct:+.1f}%"
              f" | Vol:{vol_ratio:.2f}x | Spr:{sp_disp}"
          )

          cond_vwap = session_vwap > 0 and c_close > session_vwap
          cond_ema = len(closes) >= 21 and ema9 > ema21 and c_close > ema9
          cond_vol = vol_sma20 > 0 and c_volume >= (vol_surge_mult * vol_sma20)
          cond_ext = ema9 > 0 and c_close <= (ema9 * (1.0 + max_ema_ext_pct))
          cond_spread = valid_depth and ltp_now > 0 and spread_now <= (ltp_now * 0.005)

          if cond_vwap and cond_ema and cond_vol and cond_ext and cond_spread:
            order_resp = broker.place_market_order(active_sym, exchange, "BUY", qty)
            if order_resp and order_resp.get("status") == "success":
              in_trade = True
              entry_price = (
                  order_resp["fill_price"]
                  if order_resp["fill_price"] > 0
                  else c_close
              )
              highest_price = entry_price

              recent_3_low = min(c["low"] for c in st["candles"][-3:])
              structural_sl = round(min(recent_3_low, ema21) - 0.50, 2)
              pct_cap_sl = round(entry_price * (1.0 - max_sl_pct), 2)
              initial_sl = max(structural_sl, pct_cap_sl)
              if initial_sl >= entry_price:
                initial_sl = pct_cap_sl

              stop_loss = initial_sl
              initial_risk_pts = max(0.50, round(entry_price - initial_sl, 2))
              breakeven_trigger = round(entry_price + (1.5 * initial_risk_pts), 2)
              stage2_r_trigger = round(entry_price + (2.0 * initial_risk_pts), 2)
              stage2_pct_trigger = round(entry_price * 1.50, 2)
              locked_floor = 0.0
              stage = "INITIAL_SL"
              climax_armed = False
              climax_trigger_price = None
              print(
                  f"\n>>> [CONFLUENCE ENTRY] BUY {qty} {active_sym} @ ₹{entry_price:.2f}"
                  f" | Structural SL: ₹{structural_sl:.2f} | 25% Cap: ₹{pct_cap_sl:.2f}"
                  f" | Active SL: ₹{stop_loss:.2f} (R: {initial_risk_pts:.2f} pts / ₹{initial_risk_pts*qty:.0f})"
                  f" | 1.5R BE: ₹{breakeven_trigger:.2f} | Stage2: ₹{min(stage2_r_trigger, stage2_pct_trigger):.2f} <<<"
              )
          elif cond_vwap and cond_ema:
            reasons = []
            if not cond_vol:
              reasons.append(f"Vol {vol_ratio:.2f}x < {vol_surge_mult}x")
            if not cond_ext:
              reasons.append(f"Ext {ext_pct:+.1f}% > +{max_ema_ext_pct*100:.0f}% (wait 9EMA pullback)")
            if not cond_spread:
              reasons.append(f"Spread/Depth invalid ({sp_disp})")
            if reasons:
              print(f"[SKIP CONFLUENCE | {active_sym}] " + " | ".join(reasons))

        # PHASE C: Candle-Close Staged Trailing & Climax-Wick Protection
        else:
          candles = st["candles"]
          if stage == "STAGE2_PROFIT_TRAIL" and len(candles) >= 2:
            prev_2_candle_low = min(candles[-1]["low"], candles[-2]["low"])
            trail_candidate = round(max(locked_floor, min(prev_2_candle_low, ema9 - 1.50)), 2)
            if trail_candidate > stop_loss:
              stop_loss = trail_candidate
              print(
                  f"\n[STAGE 2 TRAIL | {active_sym}] SL raised to ₹{stop_loss:.2f}"
                  f" (Floor: ₹{locked_floor:.2f} | 2C-Low: ₹{prev_2_candle_low:.2f} | 9EMA-1.50: ₹{ema9 - 1.50:.2f})"
              )

          # 1-Candle Climax Wick Verification (auto-disarms if next candle holds above trigger)
          if climax_armed:
            if c_close < climax_trigger_price:
              ok, daily_pnl, trades_today = _execute_exit(
                  broker,
                  active_sym,
                  exchange,
                  qty,
                  entry_price,
                  highest_price,
                  stage,
                  "CLIMAX_WICK_EXIT",
                  c_close,
                  charges_per_trade,
                  daily_pnl,
                  trades_today,
                  now,
              )
              if ok:
                in_trade = False
                stage = "IDLE"
                locked_floor = 0.0
                climax_armed = False
                climax_trigger_price = None
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

      if in_trade and state[active_sym]["last_quote"]:
        ltp = state[active_sym]["last_quote"]["ltp"]
        unrealized = round((ltp - entry_price) * qty, 2)
        pct = ((ltp - entry_price) / entry_price) * 100.0
        print(
            f"[{stage} | {active_sym}] LTP: {ltp:.2f} ({pct:+.1f}%)"
            f" | SL: {stop_loss:.2f} | 1.5R BE: {breakeven_trigger:.2f} | P&L: ₹{unrealized:.1f}"
        )

      time.sleep(0.05 if config.MODE == "SIMULATION" else 1.5)

  except KeyboardInterrupt:
    print("\n[STOPPED] Engine manually terminated by user.")
  finally:
    broker.shutdown()


if __name__ == "__main__":
  run_v3_engine()
