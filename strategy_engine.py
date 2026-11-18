import csv
import datetime
import os
import time
from broker_adapter import BrokerAdapter
import config


def log_trade_to_csv(
    symbol, entry_time, exit_time, entry_p, exit_p, max_p, qty, reason
):
  file_exists = os.path.isfile("paper_trades_log.csv")
  gross_pnl = round((exit_p - entry_p) * qty, 2)
  # Realistic slippage & charges deduction (approx 0.5% of turnover)
  est_charges = round((entry_p + exit_p) * qty * 0.0025, 2)
  net_pnl = round(gross_pnl - est_charges, 2)

  with open("paper_trades_log.csv", mode="a", newline="") as f:
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


def run_algo():
  broker = BrokerAdapter()
  print(
      f"=== Starting Option Algo [{config.MODE} MODE] | Symbol:"
      f" {config.SYMBOL} ==="
  )

  # State Variables
  reference_high = 0.0
  observation_ticks = 0
  in_trade = False
  entry_price = 0.0
  entry_time = ""
  current_sl = 0.0
  highest_ltp = 0.0
  breakeven_locked = False

  while True:
    now_dt = datetime.datetime.now()
    now_time = now_dt.time()

    # Live mode mein market hours check karein
    if config.MODE == "OPENALGO" and now_time < config.START_TIME:
      time.sleep(1)
      continue

    ltp = broker.get_ltp(config.SYMBOL, config.EXCHANGE)

    # PHASE 1: Observation Window (Initial Range / Reference High set karna)
    # Simulation mein pehle 10 ticks observe karega; Live mein pehle 5 mins (300 ticks)
    obs_limit = 10 if config.MODE == "SIMULATION" else 300
    if not in_trade and observation_ticks < obs_limit:
      observation_ticks += 1
      if ltp > reference_high:
        reference_high = ltp
      print(
          f"[OBSERVING {observation_ticks}/{obs_limit}] LTP: {ltp:.2f} | Ref"
          f" High: {reference_high:.2f}"
      )
      time.sleep(0.5 if config.MODE == "SIMULATION" else 1.0)
      continue

    # PHASE 2: Entry Trigger (Reference High + Buffer Breakout)
    trigger_price = round(reference_high + config.ENTRY_BUFFER_POINTS, 2)
    if not in_trade:
      if ltp >= trigger_price:
        broker.place_order(
            config.SYMBOL, config.EXCHANGE, "BUY", config.QTY, ltp
        )
        in_trade = True
        entry_price = ltp
        entry_time = now_time.strftime("%H:%M:%S")
        current_sl = round(entry_price - config.INITIAL_SL_POINTS, 2)
        highest_ltp = entry_price
        print(
            f"\n>>> [ENTRY] BUY {config.SYMBOL} @ {entry_price:.2f} | Trigger:"
            f" {trigger_price:.2f} | Initial SL: {current_sl:.2f} <<<\n"
        )
      else:
        print(
            f"[WAITING ENTRY] LTP: {ltp:.2f} | Trigger Needed:"
            f" {trigger_price:.2f}"
        )

    # PHASE 3: Active Trade Management (Strict SL + Trailing Logic)
    elif in_trade:
      if ltp > highest_ltp:
        highest_ltp = ltp

      profit_pts = highest_ltp - entry_price

      # Rule A: 1:1 Profit par Cost-to-Cost (Breakeven) SL lock karein
      if (
          config.MOVE_TO_BREAKEVEN_AT_1R
          and not breakeven_locked
          and profit_pts >= config.INITIAL_SL_POINTS
      ):
        current_sl = entry_price
        breakeven_locked = True
        print(
            f"\n>>> [SL TRAIL - BREAKEVEN] 1:1 Target Reached! SL shifted to"
            f" Entry: {current_sl:.2f} <<<\n"
        )

      # Rule B: Breakeven ke baad har TRAIL_STEP_POINTS par SL upar shift karein
      elif breakeven_locked:
        extra_profit = profit_pts - config.INITIAL_SL_POINTS
        steps = int(extra_profit // config.TRAIL_STEP_POINTS)
        proposed_sl = round(entry_price + (steps * config.TRAIL_STEP_POINTS), 2)
        if proposed_sl > current_sl:
          current_sl = proposed_sl
          print(
              f"\n>>> [SL TRAIL - STEP] High: {highest_ltp:.2f} | New Trailed"
              f" SL: {current_sl:.2f} <<<\n"
          )

      unrealized_pnl = round((ltp - entry_price) * config.QTY, 2)
      print(
          f"[IN TRADE] LTP: {ltp:.2f} | Entry: {entry_price:.2f} | SL:"
          f" {current_sl:.2f} | Peak: {highest_ltp:.2f} | Live P&L:"
          f" ₹{unrealized_pnl}"
      )

      # Rule C: Strict SL Hit Check
      if ltp <= current_sl:
        broker.place_order(
            config.SYMBOL, config.EXCHANGE, "SELL", config.QTY, ltp
        )
        exit_time = now_time.strftime("%H:%M:%S")
        reason = "Trailed SL Hit" if breakeven_locked else "Initial Strict SL Hit"
        print(f"\n>>> [EXIT - {reason}] Sold @ {ltp:.2f} <<<")
        log_trade_to_csv(
            config.SYMBOL,
            entry_time,
            exit_time,
            entry_price,
            ltp,
            highest_ltp,
            config.QTY,
            reason,
        )
        break

      # Rule D: EOD Square-Off Check (Live Mode)
      if config.MODE == "OPENALGO" and now_time >= config.SQUARE_OFF_TIME:
        broker.place_order(
            config.SYMBOL, config.EXCHANGE, "SELL", config.QTY, ltp
        )
        exit_time = now_time.strftime("%H:%M:%S")
        print(f"\n>>> [EXIT - EOD SQUARE OFF] Sold @ {ltp:.2f} <<<")
        log_trade_to_csv(
            config.SYMBOL,
            entry_time,
            exit_time,
            entry_price,
            ltp,
            highest_ltp,
            config.QTY,
            "EOD Square-Off",
        )
        break

    time.sleep(0.5 if config.MODE == "SIMULATION" else 1.0)


if __name__ == "__main__":
  run_algo()
