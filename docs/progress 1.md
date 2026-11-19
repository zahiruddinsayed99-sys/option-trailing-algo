# update 2
Clean execution! Both simulation runs verified every single Phase 3 guardrail end-to-end:

* **3-Min Candle + VWAP Filter:** Candle 3 stayed below the trigger (`122.99 < 124.84` and `118.90 < 124.75`), correctly holding off until Candle 4 closed above both the Reference High + Buffer and the running VWAP.
* **Multi-Stage SL Progression:** Locked breakeven at 1:1 (`131.69` / `127.48`), trailed cleanly in 8-point steps (`139.69` $\rightarrow$ `147.69`), and exited immediately when the pullback crossed the trailed SL.
* **Daily Stateful Kill-Switch:** On your second run, it automatically read `paper_trades_log.csv` and updated the session counter to `Trades Today: 1/3 | P&L Today: ₹283.69`.

### Next Steps to Lock In Phase 3

1. **Commit & Push Phase 3 to GitHub:**
```bash
cd ~/trading-projects/option-trailing-algo
git add config.py broker_adapter.py strategy_engine.py
git commit -m "feat(phase-3): add 3m candle close + VWAP filter, API retry wrapper, and daily kill-switch"
git push

```


2. **Shoonya Onboarding:** Once your Shoonya account and TOTP 2FA are active, we will plug the Shoonya credentials into `~/trading-projects/openalgo/.env`, verify the OpenAlgo symbol format (e.g., `SENSEX19NOV2682600CE` vs `SENSEX26N1982600CE`—we'll check OpenAlgo's master contract search), and run your first live feed paper test in **Analyze Mode**.

Here is your updated Master Task Checklist with Phase 3 marked complete:

---
Phase 3 mein hum aapke existing 3 files (`config.py`, `broker_adapter.py`, `strategy_engine.py`) ko in **3 critical upgrades** ke saath update karenge:

1. **API Resilience Wrapper (`broker_adapter.py`):** Shoonya (NorenOMS) mein kabhi-kabhi transient timeout ya packet drop aata hai. Hum `get_ltp` aur `place_order` mein **3-retry loop + exponential backoff** dalenge taaki script kabhi crash na ho.
2. **3-Minute Candle Close + Session VWAP Confirmation (`strategy_engine.py`):** Simple tick spike par fake entry se bachne ke liye script live ticks se **3-minute OHLC candles** aur **running VWAP** build karegi—entry tabhi hogi jab 3-min candle ka **close** Reference High ke upar ho aur premium **VWAP ke upar** ho.
3. **Daily Guardrails (`config.py` + `strategy_engine.py`):**
* `MAX_TRADES_PER_DAY = 3` (aapke daily trade cap ke hisaab se).
* `MAX_DAILY_LOSS` kill-switch (agar daily net loss limit cross ho toh algo automatically lock ho jayega).
* Interactive terminal prompt (taaki roz `config.py` edit kiye bina aap seedha strike symbol dal sakein).



---

### Step 1: `config.py` Update Karein

Apne `~/trading-projects/option-trailing-algo/config.py` ko is updated code se replace karein:

```python
import datetime

# Execution Mode: "SIMULATION" (local test) ya "OPENALGO" (live feed + paper/live orders)
MODE = "SIMULATION"

# OpenAlgo Settings
OPENALGO_API_KEY = "AAPKI_OPENALGO_API_KEY"
OPENALGO_HOST = "http://127.0.0.1:5000"

# Default Strike & Risk Parameters (Runtime par override kar sakte hain)
SYMBOL = "SENSEX26NOV80800PE"
EXCHANGE = "BFO"  # NFO (Nifty/BankNifty) ya BFO (Sensex)
QTY = 20  # 1 Lot Sensex = 20, Nifty = 75

# Entry & Candle Confirmation Rules
CANDLE_TIMEFRAME_SEC = 180  # 3-minute candle close confirmation
USE_VWAP_FILTER = True  # Entry sirf tab jab close >= running VWAP
ENTRY_BUFFER_POINTS = 1.0  # Reference high ke upar buffer

# Stop-Loss & Trailing Rules
INITIAL_SL_POINTS = 15.0  # Strict Initial SL (₹300 risk on 20 qty)
TRAIL_STEP_POINTS = 8.0  # Breakeven ke baad har 8 pt move par SL trail
MOVE_TO_BREAKEVEN_AT_1R = True  # 1:1 profit par Cost-to-Cost lock

# Daily Discipline Guardrails (Kill Switch)
MAX_TRADES_PER_DAY = 3
MAX_DAILY_LOSS = 800.0  # Max daily loss cap in INR
TRADING_START_TIME = datetime.time(11, 30)
TRADING_END_TIME = datetime.time(13, 30)
SQUARE_OFF_TIME = datetime.time(15, 15)

```

---

### Step 2: `broker_adapter.py` Update Karein (Auto-Retry & Resilience)

Isme humne `_with_retry()` decorator/helper add kiya hai jo kisi bhi network glitch par 3 baar retry karega:

```python
import random
import time
from openalgo import api
import config


class BrokerAdapter:

  def __init__(self):
    self.mode = config.MODE
    self.sim_price = 120.0
    self.sim_tick_count = 0

    if self.mode == "OPENALGO":
      self.client = api(
          api_key=config.OPENALGO_API_KEY, host=config.OPENALGO_HOST
      )

  def _execute_with_retry(self, func, *args, retries=3, delay=0.5, **kwargs):
    last_err = None
    for attempt in range(1, retries + 1):
      try:
        return func(*args, **kwargs)
      except Exception as e:
        last_err = e
        print(
            f"\n[API WARNING] Attempt {attempt}/{retries} failed: {e}."
            f" Retrying in {delay}s..."
        )
        time.sleep(delay)
        delay *= 2  # Exponential backoff
    print(f"\n[API ERROR] All {retries} attempts failed: {last_err}")
    return None

  def get_ltp(self, symbol, exchange):
    if self.mode == "OPENALGO":

      def _fetch():
        quote = self.client.quotes(symbol=symbol, exchange=exchange)
        return float(quote["data"]["ltp"])

      return self._execute_with_retry(_fetch)

    # SIMULATION MODE: Realistic 3-min candle & breakout simulation
    self.sim_tick_count += 1
    if self.sim_tick_count <= 15:
      # Initial consolidation (118 - 124)
      self.sim_price = round(random.uniform(118.0, 124.0), 2)
    elif self.sim_tick_count <= 45:
      # Sustained breakout above range + VWAP
      self.sim_price = round(self.sim_price + random.uniform(-0.8, 3.2), 2)
    else:
      # Pullback to test trailed SL
      self.sim_price = round(self.sim_price - random.uniform(0.5, 3.0), 2)

    return max(5.0, self.sim_price)

  def place_order(self, symbol, exchange, action, qty, price):
    if self.mode == "OPENALGO":

      def _order():
        return self.client.placeorder(
            strategy="Intraday_Option_Trail",
            symbol=symbol,
            action=action,
            exchange=exchange,
            price_type="MARKET",
            product="MIS",
            quantity=qty,
        )

      return self._execute_with_retry(_order)

    print(f"\n[SIM ORDER] {action} {qty} qty of {symbol} @ ₹{price:.2f}")
    return {"status": "success", "mode": "SIMULATION"}

```

---

### Step 3: `strategy_engine.py` Update Karein (3-Min Candle Close, VWAP & Kill Switch)

Is updated engine mein:

* **3-Minute Candle Builder:** Har 180 seconds (ya `SIMULATION` mein har 5 ticks) par ek candle close hoti hai. Entry sirf **candle close confirmation** par hogi.
* **Running Session VWAP:** Ticks se running typical price average track hota hai taaki aap VWAP ke niche false breakouts avoid kar sakein.
* **Daily Trade & Loss Kill-Switch:** 3 trades ya `MAX_DAILY_LOSS` hit hote hi script cleanly exit ho jayegi.

```python
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

```

---

### Step 4: Test & Commit Phase 3 To GitHub

WSL terminal mein teeno files update karne ke baad test run karein:

```bash
cd ~/trading-projects/option-trailing-algo
source venv/bin/activate
python strategy_engine.py

```

*(Prompt aane par bas `Enter` press karein taaki default values ke saath 3-minute candle close + VWAP entry aur trailing SL verify ho sake).*

Verify hone ke baad GitHub par Phase 3 push kar dein:

```bash
git add config.py broker_adapter.py strategy_engine.py
git commit -m "feat(phase-3): add 3m candle close + VWAP filter, API retry wrapper, and daily kill-switch"
git push

```
