# Daily Launch Cheatsheet — NSE Cash Equity Intraday Engine (V1.0)

- **Git Branch:** `dev`
- **Engine Script:** `equity_intraday_engine.py` + `equity_screener.py`
- **Trade Log:** `equity_paper_trades_log.csv`
- **Capital & Risk Budget:** `<= ₹25,000` MIS notional (`~₹5,000` margin at 5x) | `₹400` fixed risk per trade | `-₹800` daily kill-switch | `2` trades/day max

---

## Pre-Market & Morning Checklist (IST)

| Time (IST)           | Step                           | Command / Action                                                                                                                                                                                    | Verification Check                                                                                                                                                                                                |
| :------------------- | :----------------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **09:05 AM**         | **1. Verify OpenAlgo Gateway** | Ensure OpenAlgo (`http://127.0.0.1:5000`) is logged in to **Fyers** with **Analyze Mode (Purple Pill)** ON.                                                                                         | Shared gateway with Options Engine—no second OpenAlgo instance needed.                                                                                                                                            |
| **11:20 AM**         | **2. Dry-Check Market Regime** | Open a new `tmux` window (`Ctrl+B` then `C` inside `algo_sess0`):<br>`cd ~/trading-projects/option-trailing-algo && source venv/bin/activate`<br>`git checkout dev`<br>`python3 equity_screener.py` | Checks Sensex-30 constituent basket average on `NSE`:<br>• `>= +0.30%` -> **BULLISH (`LONG` Top 3 Gainers)**<br>• `<= -0.30%` -> **BEARISH (`SHORT` Top 3 Losers)**<br>• `-0.30% to +0.30%` -> **SIDEWAYS (Stand Down)** |
| **11:25 AM**         | **3. Launch Equity Engine**    | `python3 equity_intraday_engine.py`                                                                                                                                                                 | Hydrates `09:15 AM` intraday Session VWAP + `10:30–11:30 AM` Consolidation Box (`Base High` / `Base Low`) for top 3 Sensex-30 movers on `NSE`.                                                                    |
| **11:30 – 01:30 PM** | **4. Active Breakout Window**  | **Hands Off.** Scans top 3 stocks in parallel (`1` concurrent position max).                                                                                                                        | **LONG:** `Close > Base High` & `Close > VWAP` + `1.5x` Vol Surge.<br>**SHORT:** `Close < Base Low` & `Close < VWAP` + `1.5x` Vol Surge.<br>Sizes `qty = int(400 / risk_per_share)` capped at `₹25,000` notional. |
| **01:30 PM**         | **5. Entry Cutoff**            | If flat at `01:30 PM`, engine stands down automatically.                                                                                                                                            | Active trades continue trailing through `1.5R` BE, `2.5R` `+1R` lock + 2-candle swing & `9 EMA` trail, or `4.0R` target.                                                                                          |
| **03:10 PM**         | **6. EOD MIS Auto Square-Off** | Engine automatically squares off any open `LONG` or `SHORT` position at `03:10 PM` (`15:10 IST`).                                                                                                   | Executes 5–10 minutes ahead of broker MIS auto-square-off cutoff to avoid square-off penalties.                                                                                                                   |
| **03:20 PM**         | **7. Post-Market Audit**       | `cat equity_paper_trades_log.csv`                                                                                                                                                                   | Review direction (`LONG`/`SHORT`), fill price, planned `₹400` risk adherence, and net P&L.                                                                                                                        |

---

## Side-by-Side `tmux` Window Navigation (`algo_sess0`)

- **Window `0` (`main`):** Options Momentum Engine (`v3_momentum_engine.py`)
- **Window `1` (`dev`):** Cash Equity Engine (`equity_intraday_engine.py`)
- **Switch between windows:** `Ctrl+B` then `0` (Options) or `Ctrl+B` then `1` (Equity)
- **Detach safely (leave both running):** `Ctrl+B` then `D`
