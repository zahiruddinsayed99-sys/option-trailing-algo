# Daily Pre-Market to Algo Launch Master Cheatsheet
## Project: `option-trailing-algo`

**Trading Window:** 09:00 AM – 03:20 PM IST  
**Primary Objective:** Daily algo launch with minimum manual intervention, zero confusion and disciplined execution.
---
## Run 1
Here is the exact `tmux` command and step-by-step morning launch sequence for **Thursday, Nov 26, 2026 (SENSEX Expiry Day)**. Keep OpenAlgo in its own isolated `tmux` session (`openalgo`) so it never gets killed when you restart or close your trading engine session (`algo_sess0`).

---

### Step 1: Start OpenAlgo Gateway (`09:05 AM IST`)

Run this in WSL Ubuntu to launch OpenAlgo inside its dedicated `openalgo` session:

```bash
tmux kill-session -t openalgo 2>/dev/null || true
tmux new-session -d -s openalgo -c ~/trading-projects/openalgo "source venv/bin/activate && python3 app.py"
tmux attach -t openalgo

```

1. Wait until you see `Running on [http://127.0.0.1:5000](http://127.0.0.1:5000)` (and verify Fyers login in your browser at `[http://127.0.0.1:5000](http://127.0.0.1:5000)`).
2. **Detach cleanly without stopping OpenAlgo:** Press **`Ctrl + B`**, release, then press **`D`**.

---

### Step 2: Run Screeners with 60-Second Spacing (`10:15 AM IST`)

*(Spacing the two screeners by 60 seconds guarantees you stay well inside Fyers' `50 requests/min` REST limit.)*

1. **At `10:15 AM` — Screen Option Strikes (`12` REST calls):**
```bash
cd ~/trading-projects/option-trailing-algo && source venv/bin/activate
python3 strike_screener.py

```


* When prompted by **`[0-DTE EXPIRY WARNING]`**, press **`Y`** (Enter) to roll into next week's expiry (`₹4,000–₹5,500/lot` sweet spot).
* Copy the output `CANDIDATE_STRIKES = [...]` list into `config.py`.


2. **At `10:17 AM` — Screen Sensex-30 Cash Equities (`30` REST calls):**
```bash
python3 equity_screener.py

```


* Copy `EQUITY_WATCHLIST = [...]` and `EQUITY_DIRECTION = "..."` into `config.py` and save (`Ctrl + S`).



---

### Step 3: Launch Both Engines in `algo_sess0` (`10:25 AM IST`)

Run this exact block to spin up a clean two-window `tmux` session (`Window 0` = Options V3.4, `Window 1` = Cash Equity V1.0):

```bash
tmux kill-session -t algo_sess0 2>/dev/null || true
tmux new-session -d -s algo_sess0 -n options -c ~/trading-projects/option-trailing-algo "source venv/bin/activate && python3 v3_momentum_engine.py"
tmux new-window -t algo_sess0:1 -n equity -c ~/trading-projects/option-trailing-algo "source venv/bin/activate && python3 equity_intraday_engine.py"
tmux select-window -t algo_sess0:0
tmux attach -t algo_sess0

```

---

### Quick `tmux` Navigation Cheat Sheet

* **Switch between Options (`0`) and Equity (`1`):** `Ctrl + B`, then **`0`** or **`1`** (or **`N`** for next window).
* **Detach & leave both engines running hands-free:** `Ctrl + B`, then **`D`**.
* **Re-attach later to check logs:** `tmux attach -t algo_sess0`
* **Stop both engines cleanly after `01:30 PM`:** Attach to `algo_sess0`, press **`Ctrl + C`** in Window `0` and Window `1`, then `tmux kill-session -t algo_sess0`.
---

# 1. Daily Algo Launch Schedule

| Time Window (IST) | Phase | Exact Actions | Pass Criteria (Go / No-Go) |
|---|---|---|---|
| **09:00–09:15 AM** | **1. Infrastructure & Token Boot** | 1. Open WSL terminal and verify IST clock using `date`.<br>2. Start OpenAlgo gateway if not running.<br>3. Open `http://127.0.0.1:5000` in browser.<br>4. Login with Fyers for daily token refresh. | - IST clock correct.<br>- OpenAlgo shows Fyers Connected.<br>- Analyze (Paper) mode confirmed. |
| **09:15–10:15 AM** | **2. Macro & Direction Lock** | 1. No trades before 11:30 AM; observe opening volatility.<br>2. Check VIX, 15-minute index trend vs VWAP, PCR/OI buildup and top constituents volume (≥ 1.5x).<br>3. Commit to one directional bias: `CE` or `PE`. | - Clear directional bias.<br>- Never commit to both directions.<br>- Choppy/sideways market = NO-TRADE DAY. |
| **10:15–10:25 AM** | **3. Strike Selection & Quote Test** | 1. Find active expiry strike priced in ₹220–₹320 range.<br>2. Search exact option symbol through OpenAlgo.<br>3. Verify live feed, LTP, volume and bid-ask spread. | - API status: `success`.<br>- Non-zero LTP and volume.<br>- Bid-ask spread ≤ ₹1.00.<br>- Premium ₹220–₹320. |
| **10:25–10:29 AM** | **4. Config & Engine Launch** | 1. Update `SYMBOL`, `EXCHANGE`, `QTY` in `config.py`.<br>2. Launch inside `tmux`.<br>3. Activate virtual environment.<br>4. Run `v3_momentum_engine.py`. | - Engine starts successfully.<br>- `Trades: 0/3` displayed.<br>- Base collection starts before 10:30 AM. |
| **10:30–11:30 AM** | **5. Freeze Hour (Hands Off)** | 1. Bot automatically records Base High and Base Low using 3-minute candles.<br>2. Avoid manual interference.<br>3. Detach tmux using `Ctrl+B`, then `D`.<br>4. Reattach using `tmux attach -t algo_session`. | At 11:30 AM, terminal prints:<br>`>>> [11:30 BASE LOCKED] <<<` |
| **11:30 AM–01:30 PM** | **6. Automated Execution Window** | 1. Bot enters only on configured 3-minute breakout.<br>2. Risk condition must be ≤ 13%.<br>3. Manage Stage 1 (+25% BE), Stage 2 (+50% 2-candle low trail), Stage 3 (9 EMA), Stage 4 (2x / climax wick).<br>4. Follow configured EOD square-off. | - No manual SL overrides.<br>- No premature exits.<br>- Follow configured execution rules. |
| **03:20 PM** | **7. EOD CSV Audit** | 1. Inspect today's trade log.<br>2. Check OpenAlgo Orderbook status.<br>3. Share CSV row and execution details for daily review. | Audit progress toward the 15–20 paper-trade validation milestone. |

---

# 2. Infrastructure & Daily Token Boot

## Step 1: Open WSL and Verify IST Clock

```bash
date
```

Confirm the system clock is showing the correct Indian Standard Time.

## Step 2: Start OpenAlgo Gateway

```bash
cd ~/trading-projects/openalgo
source venv/bin/activate
python3 app.py
```

Keep the OpenAlgo gateway running.

## Step 3: Login with Fyers

Open browser:

`http://127.0.0.1:5000`

Perform the following:

1. Login with Fyers.
2. Complete daily authentication/token refresh.
3. Confirm Fyers Connected.
4. Confirm Analyze (Paper) mode.
5. Verify the gateway is operational.

**GO:** Connection and authentication confirmed.

**NO-GO:** Authentication failure, disconnected broker or uncertain execution mode.

---

# 3. Macro Analysis & Direction Selection

**Time:** 09:15–10:15 AM

No trades are permitted before 11:30 AM under this workflow.

Collect the following market information:

| Parameter | What to Check | Purpose |
|---|---|---|
| India VIX | Current level and movement | Understand volatility conditions. |
| Index Trend | 15-minute chart | Establish directional structure. |
| VWAP | Index price above/below VWAP | Assess directional confirmation. |
| PCR | Put/Call Ratio | Market positioning context. |
| OI Buildup | Call and Put OI changes | Identify positioning and potential resistance/support. |
| Constituent Volume | Relative volume ≥ 1.5x | Confirm participation. |

## Direction Lock

Select only one directional bias:

- `CE` – Bullish bias.
- `PE` – Bearish bias.
- `NO TRADE` – Unclear, conflicting or sideways market.

**Important:** Directional bias is not an automatic entry signal. The actual engine entry conditions must independently pass.

---

# 4. Strike Selection & Live Quote Verification

**Time:** 10:15–10:25 AM

## Selection Parameters

| Parameter | Target / Requirement |
|---|---|
| Instrument | SENSEX / NIFTY |
| Option Type | CE or PE |
| Expiry | Active expiry |
| Premium | ₹220–₹320 |
| Maximum bid-ask spread | ₹1.00 |
| SENSEX lot quantity | 20 (verify current contract master) |
| NIFTY lot quantity | 65 (verify current contract master) |
| Daily loss cap | ₹800 |
| Maximum trades | 3, as configured |

## Step 1: Activate Trading Project

```bash
cd ~/trading-projects/option-trailing-algo
source venv/bin/activate
```

## Step 2: Search Exact Option Symbol

Example SENSEX symbol search:

```bash
python3 -c "from openalgo import api; import config; c=api(api_key=config.OPENALGO_API_KEY, host=config.OPENALGO_HOST); print(c.search(query='SENSEX 84100', exchange='BFO'))"
```

Verify the returned symbol against the active exchange contract master.

## Step 3: Verify Live Quote

Example:

```bash
python3 -c "from openalgo import api; import config; c=api(api_key=config.OPENALGO_API_KEY, host=config.OPENALGO_HOST); print(c.quotes(symbol='SENSEX26NOV2684100CE', exchange='BFO'))"
```

Verify:

- API status is `success`.
- LTP is non-zero.
- Volume is non-zero.
- Bid and ask prices are available.
- Bid-ask spread is within the configured limit.
- Premium is within the selected range.
- Symbol and expiry are correct.

**NO-GO:** Stale quote, missing volume, incorrect symbol, illiquid contract or excessive spread.

---

# 5. Configuration & Engine Launch

**Time:** 10:25–10:29 AM

Open:

`config.py`

Update the following parameters:

| Variable | Required Input |
|---|---|
| `SYMBOL` | Selected option trading symbol |
| `EXCHANGE` | `BFO` / `NFO` |
| `QTY` | Applicable contract quantity |

Before launch, verify the daily risk configuration and instrument details.

## Step 1: Start tmux Session

```bash
tmux new -s algo_session
```

## Step 2: Activate Trading Environment

```bash
cd ~/trading-projects/option-trailing-algo
source venv/bin/activate
```

## Step 3: Launch Momentum Engine

```bash
python3 v3_momentum_engine.py
```

## Expected Startup Checks

- Engine starts without Python errors.
- Correct symbol is displayed.
- Correct exchange is displayed.
- Correct quantity is displayed.
- `Trades: 0/3` is displayed.
- Base collection starts before 10:30 AM.

Do not proceed if the engine displays incorrect configuration or an unexpected error.

---

# 6. Freeze Hour – Base High & Base Low Collection

**Time:** 10:30–11:30 AM

During this period:

1. Engine collects 3-minute candles.
2. Records Base High.
3. Records Base Low.
4. Maintains the base according to the configured algorithm.
5. Waits for the 11:30 AM base lock.

Expected terminal message:

```text
>>> [11:30 BASE LOCKED] <<<
```

## tmux Session Management

| Action | Command |
|---|---|
| Detach session | `Ctrl+B`, then `D` |
| Reattach session | `tmux attach -t algo_session` |
| List sessions | `tmux ls` |

**Important:** Detaching tmux does not stop the engine. Keep the WSL environment and gateway running.

---

# 7. Automated Execution Window

**Time:** 11:30 AM–01:30 PM

The engine follows its configured entry and trade-management rules.

## Entry Conditions

| Condition | Rule |
|---|---|
| Trading window | 11:30 AM onwards |
| Candle timeframe | 3 minutes |
| Breakout condition | 3-minute close above Base High, as configured |
| Risk filter | ≤ 13%, as configured |
| Trade limit | Maximum 3 trades, as configured |

## Trade Management Stages

| Stage | Trigger | Action |
|---|---|---|
| Stage 1 | +25% | Move SL to Break-even (BE). |
| Stage 2 | +50% | Trail using 2-candle low. |
| Stage 3 | Trend management | Use 9 EMA trailing. |
| Stage 4 | 2x gain / climax wick | Apply configured exit logic. |
| EOD | 03:15 PM | Square-off as configured. |

## Execution Discipline

- No manual SL overrides.
- No emotional or premature exits.
- No additional discretionary trades.
- Monitor connectivity and position reconciliation.
- Verify every order's actual status.
- Stop the engine safely if position or order status becomes uncertain.

---

# 8. End-of-Day CSV Audit

**Time:** 03:20 PM

## Step 1: Inspect Trade Log

```bash
cat v3_paper_trades_log.csv
```

## Step 2: Collect Execution Details

Record:

1. Trade date.
2. Trading symbol.
3. CE / PE direction.
4. Entry time.
5. Entry premium.
6. Exit time.
7. Exit premium.
8. Initial SL.
9. Break-even movement.
10. Trailing SL changes.
11. Final exit reason.
12. Gross P&L.
13. Net P&L, where available.
14. Order execution status.
15. Any errors or rejected orders.

## Step 3: Daily Review

Share the following for review:

- Today's CSV trade log.
- OpenAlgo Orderbook status.
- Entry and exit details.
- Any execution errors.
- Engine terminal logs, if required.

## Validation Milestone

Target: **15–20 paper trades** before considering any live deployment.

Evaluate:

- Win rate.
- Average winning trade.
- Average losing trade.
- Risk-reward ratio.
- Maximum drawdown.
- SL execution reliability.
- Trailing effectiveness.
- Slippage.
- Order failures.
- Rule adherence.

Do not consider the strategy validated merely because it produces a few profitable trades.

---

# 9. Complete Daily Go / No-Go Checklist

## Infrastructure

- [ ] WSL running.
- [ ] IST clock verified.
- [ ] OpenAlgo gateway running.
- [ ] Fyers authentication refreshed.
- [ ] Fyers Connected confirmed.
- [ ] Analyze / Paper mode confirmed.

## Market Analysis

- [ ] VIX checked.
- [ ] 15-minute index trend checked.
- [ ] VWAP direction checked.
- [ ] PCR checked.
- [ ] OI buildup checked.
- [ ] Constituent volume checked.
- [ ] CE / PE directional bias selected.
- [ ] No-trade conditions evaluated.

## Contract Selection

- [ ] Active expiry verified.
- [ ] Exact symbol verified.
- [ ] Correct exchange verified.
- [ ] Premium within ₹220–₹320.
- [ ] Bid-ask spread ≤ ₹1.00.
- [ ] Live LTP verified.
- [ ] Volume verified.
- [ ] Lot quantity verified.
- [ ] Daily loss cap verified.

## Engine Launch

- [ ] `config.py` updated.
- [ ] SYMBOL correct.
- [ ] EXCHANGE correct.
- [ ] QTY correct.
- [ ] tmux session created.
- [ ] Engine launched.
- [ ] No Python errors.
- [ ] `Trades: 0/3` confirmed.
- [ ] Base collection started.

## Trading & Audit

- [ ] 11:30 AM Base Locked confirmed.
- [ ] Execution conditions monitored.
- [ ] No unauthorized manual overrides.
- [ ] Trade limits respected.
- [ ] All orders reconciled.
- [ ] EOD square-off verified.
- [ ] CSV audit completed.
- [ ] Daily performance reviewed.

---

# 10. Quick Copy-Paste Command to Create This File

Run this command in WSL to create the Markdown file directly inside the GitHub project repository.

```bash
cd ~/trading-projects/option-trailing-algo

cat << 'EOF' > DAILY_LAUNCH_CHEATSHEET.md
# Daily Pre-Market to Algo Launch Master Cheatsheet
## Project: option-trailing-algo
## Trading Window: 09:00 AM – 03:20 PM IST

## 1. 09:00–09:15 AM: Infrastructure & Token Boot
- Verify IST clock: `date`
- Start OpenAlgo:
  `cd ~/trading-projects/openalgo`
  `source venv/bin/activate`
  `python3 app.py`
- Open `http://127.0.0.1:5000`
- Login with Fyers.
- Confirm Fyers Connected and Analyze (Paper) mode.

## 2. 09:15–10:15 AM: Macro & Direction Lock
- No trades before 11:30 AM.
- Check VIX.
- Check 15-minute index trend vs VWAP.
- Check PCR and OI buildup.
- Check constituent volume (>= 1.5x).
- Lock one direction: CE or PE.
- Choppy/sideways market = NO TRADE.

## 3. 10:15–10:25 AM: Strike Selection & Quote Test
- Activate project:
  `cd ~/trading-projects/option-trailing-algo`
  `source venv/bin/activate`
- Search exact symbol using OpenAlgo.
- Verify active expiry and exchange.
- Check live LTP and volume.
- Verify bid-ask spread <= ₹1.00.
- Target premium: ₹220–₹320.

## 4. 10:25–10:29 AM: Config & Engine Launch
- Update SYMBOL, EXCHANGE and QTY in config.py.
- Verify current exchange lot size.
- Start tmux:
  `tmux new -s algo_session`
- Activate virtual environment.
- Run:
  `python3 v3_momentum_engine.py`
- Confirm `Trades: 0/3`.

## 5. 10:30–11:30 AM: Freeze Hour
- Collect Base High and Base Low.
- Use configured 3-minute candles.
- Wait for `[11:30 BASE LOCKED]`.
- Avoid manual interference.

## 6. 11:30 AM–01:30 PM: Automated Execution
- Follow configured 3-minute breakout condition.
- Apply configured risk filter.
- Stage 1: +25% Break-even.
- Stage 2: +50% 2-candle low trail.
- Stage 3: 9 EMA trailing.
- Stage 4: 2x / climax wick exit logic.
- Follow configured EOD square-off.
- Reconcile all orders and positions.

## 7. 03:20 PM: EOD Audit
- Inspect:
  `cat v3_paper_trades_log.csv`
- Check OpenAlgo Orderbook.
- Record entries, exits, SL movements and P&L.
- Share CSV and execution details for review.
- Target 15–20 paper trades for validation.

## Safety Rules
- Paper mode until strategy validation is complete.
- Verify symbol, expiry, lot size and live quotes.
- Never assume API success means order execution.
- Stop the engine if data, connectivity or position reconciliation fails.
- No valid setup = NO TRADE.
- No verified connection = NO LAUNCH.
- No reconciled position = STOP ENGINE.
EOF
```

---

# 11. Critical Technical & Operational Verification

Before moving from paper to live execution, independently verify these items against the actual engine code and current exchange/broker specifications:

| Item | Verification Required |
|---|---|
| ₹800 daily loss cap | Confirm whether it includes charges, slippage and open-position risk. |
| 13% risk condition | Confirm the denominator and whether it applies to premium loss or another risk measure. |
| ₹220–₹320 premium | Confirm this is a selection preference, not a guaranteed risk limit. |
| SENSEX / NIFTY lot size | Verify against current exchange contract specifications. |
| Symbol format | Verify exact expiry and strike using current contract master. |
| ₹1 spread | Confirm tick-size and liquidity suitability. |
| Base High / Low | Verify exact candle collection and locking logic. |
| Breakout entry | Confirm candle-close condition and order execution logic. |
| Stage 1–4 | Verify actual SL calculations and order modifications. |
| 03:15 PM square-off | Confirm all open positions are reconciled and closed. |
| Paper mode | Verify that no live order can accidentally be submitted. |

**Golden Rule:** No valid setup = No Trade. No verified connection = No Launch. No reconciled position = Stop Engine.

**Document Status:** Daily operational reference. Strategy parameters must be verified against the actual code before live deployment.
