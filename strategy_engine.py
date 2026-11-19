import csv
import datetime
import os
import time
from broker_adapter import BrokerAdapter
import config


def get_today_stats(csv_file="paper_trades_log.csv"):
  """Aaj ke completed trades aur total Net P&L check karta hai."""
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


def log_trade_to_csv(
    symbol, entry_time, exit_time, entry_p, exit_p, max_p, qty, reason
):
  csv_file = "paper_trades_log.csv"
  file_exists = os.path.isfile(csv_file)
  gross_pnl = round((exit_p - entry_p) * qty, 2)
  est_charges = round((entry_p + exit_p) * qty * 0.0025, 2)
  net_pnl = round(gross_pnl - est_charges, 2)

  with open(csv_file, mode="a", newline="") as f:
    writer = csv.writer(f)
    if not file_exists:
      writer.writerow([
          "Date",
          "Symbol",
          "Entry_Time",
          "Exit_Time",
          "Entry_Price",
          "Exit_Price",
          "Highest_Price",
          "Qty",
          "Gross_PnL",
          "Net_PnL",
          "Exit_Reason",
      ])
    writer.writerow([
        datetime.date.today(),
        symbol,
        entry_time,
        exit_time,
        entry_p,
        exit_p,
        max_p,
        qty,
        gross_pnl,
        net_pnl,
        reason,
    ])
  print(f"\n[CSV LOGGED] Gross P&L: ₹{gross_pnl} | Net P&L: ₹{net_pnl}")
  return net_pnl


def prompt_runtime_inputs():
  print("\n--- Daily Strike Setup (Press Enter to keep config default) ---")
  sym = input(f"Strike Symbol [{config.SYMBOL}]: ").strip().upper()
  exch = input(f"Exchange [{config.EXCHANGE}]: ").strip().upper()
  sl_in = input(f"Initial SL Points [{config.INITIAL_SL_POINTS}]: ").strip()
  trail_in = input(f"Trail Step Points [{config.TRAIL_STEP_POINTS}]: ").strip()

  symbol = sym if sym else config.SYMBOL
  exchange = exch if exch else config.EXCHANGE
  sl_pts = float(sl_in) if sl_in else config.INITIAL_SL_POINTS
  trail_pts = float(trail_in) if trail_in else config.TRAIL_STEP_POINTS
  return symbol, exchange, sl_pts, trail_pts


def run_algo():
  # Step 1: Daily Kill-Switch Check
  trades_today, pnl_today = get_today_stats()
  if trades_today >= config.MAX_TRADES_PER_DAY:
    print(
        f"[KILL SWITCH] Max daily trades ({config.MAX_TRADES_PER_DAY})"
        " reached. Exiting."
    )
    return
  if pnl_today <= -abs(config.MAX_DAILY_LOSS):
    print(
        f"[KILL SWITCH] Max daily loss limit (-₹{config.MAX_DAILY_LOSS})"
        f" breached (Current: ₹{pnl_today}). Exiting."
    )
    return

  symbol, exchange, sl_points, trail_step = prompt_runtime_inputs()
  broker = BrokerAdapter()
  print(
      f"\n=== Running Algo [{config.MODE}] | {symbol} ({exchange}) | Trades"
      f" Today: {trades_today}/{config.MAX_TRADES_PER_DAY} | P&L Today:"
      f" ₹{pnl_today} ==="
  )

  # Candle & VWAP State
  candle_ticks = []
  ticks_per_candle = 5 if config.MODE == "SIMULATION" else 180
  completed_candles = 0
  reference_high = 0.0
  vwap_sum = 0.0
  vwap_count = 0

  # Trade State
  in_trade = False
  entry_price = 0.0
  entry_time = ""
  current_sl = 0.0
  highest_ltp = 0.0
  breakeven_locked = False

  while True:
    now_dt = datetime.datetime.now()
    now_time = now_dt.time()

    # Live mode session window enforcement
    if config.MODE == "OPENALGO":
      if not in_trade and now_time < config.TRADING_START_TIME:
        print(
            f"Waiting for trading window ({config.TRADING_START_TIME})...",
            end="\r",
        )
        time.sleep(1)
        continue
      if not in_trade and now_time > config.TRADING_END_TIME:
        print(
            "\n[SESSION END] Past new-entry cutoff"
            f" ({config.TRADING_END_TIME}). No new trades."
        )
        break

    ltp = broker.get_ltp(symbol, exchange)
    if ltp is None:
      time.sleep(1)
      continue

    # Update Running Session VWAP
    vwap_sum += ltp
    vwap_count += 1
    running_vwap = round(vwap_sum / vwap_count, 2)

    # Build 3-Min Candle
    candle_ticks.append(ltp)
    candle_closed = len(candle_ticks) >= ticks_per_candle

    if candle_closed:
      c_open = candle_ticks[0]
      c_high = max(candle_ticks)
      c_low = min(candle_ticks)
      c_close = candle_ticks[-1]
      completed_candles += 1
      candle_ticks = []

      # First 2 candles build Reference High
      if completed_candles <= 2:
        reference_high = max(reference_high, c_high)
        print(
            f"[CANDLE {completed_candles}/2] Close: {c_close:.2f} | Ref High"
            f" Updated: {reference_high:.2f} | VWAP: {running_vwap:.2f}"
        )
        continue

      # ENTRY CHECK ON 3-MIN CANDLE CLOSE
      if not in_trade and completed_candles > 2:
        trigger_level = round(reference_high + config.ENTRY_BUFFER_POINTS, 2)
        vwap_ok = (c_close >= running_vwap) if config.USE_VWAP_FILTER else True

        if c_close >= trigger_level and vwap_ok:
          res = broker.place_order(symbol, exchange, "BUY", config.QTY, ltp)
          if res:
            in_trade = True
            entry_price = ltp
            entry_time = now_time.strftime("%H:%M:%S")
            current_sl = round(entry_price - sl_points, 2)
            highest_ltp = entry_price
            print(
                f"\n>>> [3M CANDLE BREAKOUT ENTRY] BUY {symbol} @"
                f" {entry_price:.2f} | Close: {c_close:.2f} > Trigger:"
                f" {trigger_level:.2f} | VWAP: {running_vwap:.2f} | SL:"
                f" {current_sl:.2f} <<<\n"
            )
        else:
          print(
              f"[CANDLE {completed_candles} CLOSE] Close: {c_close:.2f} |"
              f" Trigger: {trigger_level:.2f} | VWAP: {running_vwap:.2f} (No"
              " Entry)"
          )

    # ACTIVE TRADE MANAGEMENT (Tick-by-Tick Strict SL & Trail)
    if in_trade:
      if ltp > highest_ltp:
        highest_ltp = ltp

      profit_pts = highest_ltp - entry_price

      # 1:1 Breakeven Lock
      if (
          config.MOVE_TO_BREAKEVEN_AT_1R
          and not breakeven_locked
          and profit_pts >= sl_points
      ):
        current_sl = entry_price
        breakeven_locked = True
        print(
            "\n>>> [SL TRAIL - BREAKEVEN] 1:1 Hit! SL locked at Entry:"
            f" {current_sl:.2f} <<<\n"
        )

      # Step Trailing SL
      elif breakeven_locked:
        extra_profit = profit_pts - sl_points
        steps = int(extra_profit // trail_step)
        proposed_sl = round(entry_price + (steps * trail_step), 2)
        if proposed_sl > current_sl:
          current_sl = proposed_sl
          print(
              f"\n>>> [SL TRAIL - STEP] Peak: {highest_ltp:.2f} | New SL:"
              f" {current_sl:.2f} <<<\n"
          )

      unrealized = round((ltp - entry_price) * config.QTY, 2)
      print(
          f"[IN TRADE] LTP: {ltp:.2f} | SL: {current_sl:.2f} | VWAP:"
          f" {running_vwap:.2f} | Live P&L: ₹{unrealized}"
      )

      # Strict SL Hit
      if ltp <= current_sl:
        broker.place_order(symbol, exchange, "SELL", config.QTY, ltp)
        exit_time = now_time.strftime("%H:%M:%S")
        reason = "Trailed SL Hit" if breakeven_locked else "Initial Strict SL Hit"
        print(f"\n>>> [EXIT - {reason}] Sold @ {ltp:.2f} <<<")
        log_trade_to_csv(
            symbol,
            entry_time,
            exit_time,
            entry_price,
            ltp,
            highest_ltp,
            config.QTY,
            reason,
        )
        break

      # EOD Auto Square-off
      if config.MODE == "OPENALGO" and now_time >= config.SQUARE_OFF_TIME:
        broker.place_order(symbol, exchange, "SELL", config.QTY, ltp)
        exit_time = now_time.strftime("%H:%M:%S")
        print(f"\n>>> [EXIT - EOD SQUARE OFF] Sold @ {ltp:.2f} <<<")
        log_trade_to_csv(
            symbol,
            entry_time,
            exit_time,
            entry_price,
            ltp,
            highest_ltp,
            config.QTY,
            "EOD Square-Off",
        )
        break

    time.sleep(0.3 if config.MODE == "SIMULATION" else 1.0)


if __name__ == "__main__":
  run_algo()