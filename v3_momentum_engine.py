import csv
import datetime
import os
import time
from broker_adapter import BrokerAdapter
import config

# ==========================================
# V3 EMOTION-DISCIPLINE PROTOCOL PARAMETERS
# ==========================================
MAX_SL_POINTS = 25.0  # Max ₹500 risk on 20 qty SENSEX (caps wide bases cleanly)
MAX_CHASE_PCT = 0.05  # Skip candle if close jumps > 5% above Base High
MAX_SPREAD_INDEX = 1.00  # Max Bid-Ask spread for SENSEX/NIFTY (₹)
MAX_SPREAD_STOCK = 0.15  # Max Bid-Ask spread for Stock Options (₹)
STAGE1_TRIGGER_PCT = 0.25  # +25% move -> Shift SL to Cost-to-Cost (Breakeven)
STAGE2_TRIGGER_PCT = 0.50  # +50% move -> Trail by Last 2-Candle Low (min +25% locked)
STAGE2_LOCK_PCT = 0.25  # Minimum +25% profit floor once Stage 2 activates
TARGET_2X_MULTIPLIER = 2.0  # +100% (2x) hard profit target
EMA_PERIOD = 9  # 9 EMA on 3-minute candle closes
UPPER_WICK_RATIO = 2.0  # Upper wick >= 2x body signals climax exhaustion


def calculate_ema(closes, period=9):
  if len(closes) < period:
    return None
  k = 2 / (period + 1)
  ema = sum(closes[:period]) / period
  for price in closes[period:]:
    ema = (price * k) + (ema * (1 - k))
  return round(ema, 2)


def get_today_stats(csv_file="v3_paper_trades_log.csv"):
  if not os.path.isfile(csv_file):
    return 0, 0.0
  today_str = str(datetime.date.today())
  trades = 0
  total_pnl = 0.0
  with open(csv_file, mode="r") as f:
    reader = csv.DictReader(f)
    for row in reader:
      if row.get("Date") == today_str:
        trades += 1
        total_pnl += float(row.get("Net_PnL", 0.0))
  return trades, round(total_pnl, 2)


def log_v3_trade(
    symbol,
    entry_time,
    exit_time,
    entry_p,
    exit_p,
    initial_sl,
    max_p,
    qty,
    stage_reached,
    reason,
):
  csv_file = "v3_paper_trades_log.csv"
  file_exists = os.path.isfile(csv_file)
  gross_pnl = round((exit_p - entry_p) * qty, 2)
  est_charges = round((entry_p + exit_p) * qty * 0.0025, 2)
  net_pnl = round(gross_pnl - est_charges, 2)
  risk_pct = round(((entry_p - initial_sl) / entry_p) * 100, 2)

  with open(csv_file, mode="a", newline="") as f:
    writer = csv.writer(f)
    if not file_exists:
      writer.writerow([
          "Date",
          "Symbol",
          "Entry_Time",
          "Exit_Time",
          "Entry_Price",
          "Initial_SL",
          "Risk_Pct",
          "Exit_Price",
          "Highest_Price",
          "Qty",
          "Gross_PnL",
          "Net_PnL",
          "Highest_Stage",
          "Exit_Reason",
      ])
    writer.writerow([
        datetime.date.today(),
        symbol,
        entry_time,
        exit_time,
        entry_p,
        initial_sl,
        risk_pct,
        exit_p,
        max_p,
        qty,
        gross_pnl,
        net_pnl,
        stage_reached,
        reason,
    ])
  print(
      f"\n[V3 CSV LOGGED] Gross P&L: ₹{gross_pnl} | Net P&L: ₹{net_pnl} | Stage:"
      f" {stage_reached}"
  )


def run_v3_strategy():
  trades_today, pnl_today = get_today_stats()
  if trades_today >= config.MAX_TRADES_PER_DAY:
    print(
        f"[KILL SWITCH] Max daily trades ({config.MAX_TRADES_PER_DAY})"
        " reached. Exiting."
    )
    return
  if pnl_today <= -abs(config.MAX_DAILY_LOSS):
    print(
        f"[KILL SWITCH] Max daily loss (-₹{config.MAX_DAILY_LOSS}) breached."
        " Exiting."
    )
    return

  print("\n=== V3 EMOTION-FREE MOMENTUM ENGINE SETUP ===")
  sym_in = input(f"Candidate Strike [{config.SYMBOL}]: ").strip().upper()
  exch_in = input(f"Exchange [{config.EXCHANGE}]: ").strip().upper()
  qty_in = input(f"Quantity [{config.QTY}]: ").strip()

  symbol = sym_in if sym_in else config.SYMBOL
  exchange = exch_in if exch_in else config.EXCHANGE
  qty = int(qty_in) if qty_in else config.QTY
  max_spread = (
      MAX_SPREAD_INDEX
      if any(idx in symbol for idx in ["SENSEX", "NIFTY", "BANKNIFTY"])
      else MAX_SPREAD_STOCK
  )

  broker = BrokerAdapter()
  print(
      f"\n>>> Starting V3 Engine [{config.MODE}] | {symbol} ({exchange}) | Max"
      f" SL Cap: {MAX_SL_POINTS} pts | Trades:"
      f" {trades_today}/{config.MAX_TRADES_PER_DAY} <<<"
  )

  # 3-Minute OHLC History & Base State
  candles = []
  current_ticks = []
  candle_start_dt = datetime.datetime.now()
  ticks_per_candle = 5 if config.MODE == "SIMULATION" else 180
  min_base_candles = 4

  base_high = 0.0
  base_low = float("inf")
  base_locked = False

  # Trade State
  in_trade = False
  entry_price = 0.0
  initial_sl_price = 0.0
  entry_time = ""
  current_sl = 0.0
  target_2x = 0.0
  highest_ltp = 0.0
  stage = "BASE_OBSERVATION"

  while True:
    now_dt = datetime.datetime.now()
    now_time = now_dt.time()

    # Freeze Hour & Execution Window Enforcement (Live Mode)
    if config.MODE == "OPENALGO":
      if now_time < datetime.time(10, 30):
        print("Waiting for 10:30 AM Freeze Hour observation window...", end="\r")
        time.sleep(1)
        continue
      if not in_trade and now_time > config.TRADING_END_TIME:
        print(
            "\n[SESSION END] Past 13:30 IST execution cutoff. No new trades."
        )
        break

    ltp = broker.get_ltp(symbol, exchange)
    if ltp is None:
      time.sleep(1)
      continue

    current_ticks.append(ltp)

    # ==========================================
    # 3-MINUTE CANDLE CLOSE PROCESSING (WALL-CLOCK)
    # ==========================================
    candle_ready = (
        len(current_ticks) >= ticks_per_candle
        if config.MODE == "SIMULATION"
        else (now_dt - candle_start_dt).total_seconds() >= 180
    )

    if candle_ready and current_ticks:
      candle = {
          "open": current_ticks[0],
          "high": max(current_ticks),
          "low": min(current_ticks),
          "close": current_ticks[-1],
      }
      candles.append(candle)
      current_ticks = []
      candle_start_dt = now_dt
      ema_9 = calculate_ema([c["close"] for c in candles], EMA_PERIOD)

      # PHASE A: BASE OBSERVATION (10:30-11:30 Freeze Hour OR min 4 candles if started late)
      still_building_base = (
          len(candles) <= min_base_candles
          or (config.MODE == "OPENALGO" and now_time < config.TRADING_START_TIME)
      )

      if not base_locked and still_building_base:
        base_high = max(base_high, candle["high"])
        base_low = min(base_low, candle["low"])
        print(
            f"[BASE OBSERVE #{len(candles)}] Close: {candle['close']:.2f} | Base"
            f" Range: [{base_low:.2f} - {base_high:.2f}]"
        )
        continue

      if not base_locked:
        base_locked = True
        print(
            f"\n>>> [BASE LOCKED] Breakout Trigger > {base_high:.2f} | Base"
            f" Low: {base_low:.2f} (SL capped at max {MAX_SL_POINTS} pts) <<<\n"
        )

      # PHASE B: BREAKOUT ENTRY & DUAL-CAP RISK FILTER (Execution Window 11:30 - 13:30)
      if base_locked and not in_trade:
        in_exec_window = (
            True
            if config.MODE == "SIMULATION"
            else (config.TRADING_START_TIME <= now_time <= config.TRADING_END_TIME)
        )

        if in_exec_window and candle["close"] > base_high:
          proposed_entry = candle["close"]
          chase_pct = (proposed_entry - base_high) / base_high

          if chase_pct > MAX_CHASE_PCT:
            print(
                f"\n[TRADE SKIPPED - CHASE GUARD] Close {proposed_entry:.2f} is"
                f" {chase_pct*100:.1f}% above Base High {base_high:.2f}. Waiting"
                " for next setup..."
            )
            continue

          # Cap SL at max 25 pts (₹500 on 20 qty) if Base Low is wider than ₹500 risk
          capped_sl = round(max(base_low, proposed_entry - MAX_SL_POINTS), 2)
          risk_pct = (proposed_entry - capped_sl) / proposed_entry

          res = broker.place_order(
              symbol, exchange, "BUY", qty, round(proposed_entry + 0.05, 2)
          )
          if res:
            in_trade = True
            entry_price = proposed_entry
            initial_sl_price = capped_sl
            entry_time = now_time.strftime("%H:%M:%S")
            current_sl = capped_sl
            target_2x = round(entry_price * TARGET_2X_MULTIPLIER, 2)
            highest_ltp = entry_price
            stage = "INITIAL_BASE_SL"
            print(
                f"\n>>> [V3 ENTRY] BUY {symbol} @ {entry_price:.2f} | Risk:"
                f" {risk_pct*100:.1f}% ({entry_price - current_sl:.2f} pts) |"
                f" Hard SL: {current_sl:.2f} | 2x Target: {target_2x:.2f} <<<\n"
            )
        else:
          print(
              f"[SCANNING 3M] Close: {candle['close']:.2f} | Base High:"
              f" {base_high:.2f} | 9 EMA: {ema_9}"
          )

      # PHASE C: CANDLE-CLOSE EXIT CHECKS (Stage 3: 9 EMA & Stage 4: Climax Rejection)
      elif in_trade:
        # Stage 2+: Update SL to Low of Last 2 Candles (never below +25% profit floor)
        if stage in ["STAGE_2_TRAIL", "STAGE_3_EMA_RIDE"] and len(candles) >= 2:
          last_2_low = min(candles[-1]["low"], candles[-2]["low"])
          floor_25 = round(entry_price * (1 + STAGE2_LOCK_PCT), 2)
          new_sl = round(max(last_2_low, floor_25), 2)
          if new_sl > current_sl:
            current_sl = new_sl
            print(
                "\n>>> [STAGE 2 TRAIL] SL moved to 2-Candle Low / +25% Floor:"
                f" {current_sl:.2f} <<<\n"
            )

        # Stage 3: Hold Above 9 EMA (Exit if 3m candle closes below 9 EMA once in Stage 2+)
        if (
            stage in ["STAGE_2_TRAIL", "STAGE_3_EMA_RIDE"]
            and ema_9 is not None
            and candle["close"] < ema_9
        ):
          broker.place_order(symbol, exchange, "SELL", qty, ltp)
          exit_time = now_time.strftime("%H:%M:%S")
          print(
              f"\n>>> [STAGE 3 EXIT - 9 EMA BREAK] Close {candle['close']:.2f}"
              f" < 9 EMA {ema_9:.2f} | Sold @ {ltp:.2f} <<<"
          )
          log_v3_trade(
              symbol,
              entry_time,
              exit_time,
              entry_price,
              ltp,
              initial_sl_price,
              highest_ltp,
              qty,
              stage,
              "3m Close Below 9 EMA",
          )
          break

        # Stage 4: Climax Rejection (Previous candle had extended upper wick, current breaks its low)
        if len(candles) >= 2:
          prev = candles[-2]
          prev_body = abs(prev["close"] - prev["open"])
          prev_upper_wick = prev["high"] - max(prev["open"], prev["close"])
          if (
              prev_body > 0
              and prev_upper_wick >= (UPPER_WICK_RATIO * prev_body)
              and candle["low"] < prev["low"]
          ):
            broker.place_order(symbol, exchange, "SELL", qty, ltp)
            exit_time = now_time.strftime("%H:%M:%S")
            print(
                "\n>>> [STAGE 4 EXIT - CLIMAX WICK REJECTION] Broke prev low"
                f" {prev['low']:.2f} | Sold @ {ltp:.2f} <<<"
            )
            log_v3_trade(
                symbol,
                entry_time,
                exit_time,
                entry_price,
                ltp,
                initial_sl_price,
                highest_ltp,
                qty,
                "STAGE_4_CLIMAX",
                "Climax Wick Rejection",
            )
            break

    # ==========================================
    # TICK-BY-TICK MILESTONES & HARD SL CHECKS
    # ==========================================
    if in_trade:
      if ltp > highest_ltp:
        highest_ltp = ltp

      gain_pct = (highest_ltp - entry_price) / entry_price

      # Stage 1 (+25%): Move SL to Cost-to-Cost (Risk-Free)
      if gain_pct >= STAGE1_TRIGGER_PCT and stage == "INITIAL_BASE_SL":
        current_sl = entry_price
        stage = "STAGE_1_BREAKEVEN"
        print(
            "\n>>> [STAGE 1 (+25%)] SL modified to Cost-to-Cost:"
            f" {current_sl:.2f} (100% Risk-Free) <<<\n"
        )

      # Stage 2 (+50% Move): Lock +25% floor & activate 2-Candle Low + 9 EMA trail
      if gain_pct >= STAGE2_TRIGGER_PCT and stage == "STAGE_1_BREAKEVEN":
        floor_25 = round(entry_price * (1 + STAGE2_LOCK_PCT), 2)
        last_2_low = (
            min(candles[-1]["low"], candles[-2]["low"])
            if len(candles) >= 2
            else floor_25
        )
        current_sl = round(max(floor_25, last_2_low), 2)
        stage = "STAGE_2_TRAIL"
        print(
            "\n>>> [STAGE 2 (+50%)] Locked +25% / 2-Candle Low SL:"
            f" {current_sl:.2f} | Riding 9 EMA <<<\n"
        )

      # Stage 4 (2x Target Hit)
      if ltp >= target_2x:
        broker.place_order(symbol, exchange, "SELL", qty, ltp)
        exit_time = now_time.strftime("%H:%M:%S")
        print(
            "\n>>> [STAGE 4 EXIT - 2X TARGET HIT] Double target reached! Sold @"
            f" {ltp:.2f} <<<"
        )
        log_v3_trade(
            symbol,
            entry_time,
            exit_time,
            entry_price,
            ltp,
            initial_sl_price,
            highest_ltp,
            qty,
            "STAGE_4_2X_TARGET",
            "2x Target Hit (+100%)",
        )
        break

      live_pnl = round((ltp - entry_price) * qty, 2)
      print(
          f"[{stage}] LTP: {ltp:.2f} (+{((ltp-entry_price)/entry_price)*100:.1f}%)"
          f" | SL: {current_sl:.2f} | 2x: {target_2x:.2f} | P&L: ₹{live_pnl}"
      )

      # Hard Stop-Loss Hit
      if ltp <= current_sl:
        broker.place_order(symbol, exchange, "SELL", qty, ltp)
        exit_time = now_time.strftime("%H:%M:%S")
        print(f"\n>>> [HARD SL EXIT] Triggered @ {ltp:.2f} (SL: {current_sl:.2f}) <<<")
        log_v3_trade(
            symbol,
            entry_time,
            exit_time,
            entry_price,
            ltp,
            initial_sl_price,
            highest_ltp,
            qty,
            stage,
            f"SL Hit ({stage})",
        )
        break

      # EOD Square-Off
      if config.MODE == "OPENALGO" and now_time >= config.SQUARE_OFF_TIME:
        broker.place_order(symbol, exchange, "SELL", qty, ltp)
        exit_time = now_time.strftime("%H:%M:%S")
        log_v3_trade(
            symbol,
            entry_time,
            exit_time,
            entry_price,
            ltp,
            initial_sl_price,
            highest_ltp,
            qty,
            stage,
            "EOD Square-Off",
        )
        break

    time.sleep(0.3 if config.MODE == "SIMULATION" else 1.0)


if __name__ == "__main__":
  run_v3_strategy()
