# Daily Launch Cheatsheet — Options Momentum Engine (V3.4)

- **Git Branch:** `main`
- **Engine Script:** `v3_momentum_engine.py` + `strike_screener.py`
- **Trade Log:** `v3_paper_trades_log.csv`
- **Capital & Risk Budget:** `₹4,000 – ₹5,500` per lot (`1` lot max) | `₹500` max risk per trade | `-₹800` daily kill-switch | `3` trades/day max

---

## Pre-Market & Morning Checklist (IST)

| Time (IST)           | Step                                 | Command / Action                                                                                                                        | Verification Check                                                                                                                                                                  |
| :------------------- | :----------------------------------- | :-------------------------------------------------------------------------------------------------------------------------------------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **09:05 AM**         | **1. Start OpenAlgo & Broker Login** | Start OpenAlgo server (`http://127.0.0.1:5000`), log in to **Fyers**, and verify **Analyze Mode (Purple Pill)** is ON.                  | Confirm WebSocket proxy (`ws://127.0.0.1:8765`) is active and API key matches `config_local.py`.                                                                                    |
| **10:15 AM**         | **2. Screen OTM Strikes**            | `cd ~/trading-projects/option-trailing-algo && source venv/bin/activate`<br>`git checkout main`<br>`python3 strike_screener.py`         | Enter `SENSEX` or `NIFTY`, `PE` or `CE`, and current Spot. Note the `SWEET SPOT` strikes (`₹200–₹275` SENSEX / `₹61.55–₹84.60` NIFTY). On `0-DTE`, choose `Y` for Next-Week Expiry. |
| **10:20 AM**         | **3. Update Watchlist**              | Paste the recommended `CANDIDATE_STRIKES = [...]` list into `config.py` and save (`Ctrl+S`).                                            | Ordered from closest OTM to deeper OTM for automatic premium rotation.                                                                                                              |
| **10:25 AM**         | **4. Launch Engine in `tmux`**       | `tmux new -s algo_sess0`<br>`cd ~/trading-projects/option-trailing-algo && source venv/bin/activate`<br>`python3 v3_momentum_engine.py` | Confirm `[BROKER] OpenAlgo WebSocket connected` and `[LIVE TICK]` heartbeat updates cleanly. Detach safely with `Ctrl+B` then `D`.                                                  |
| **10:30 – 11:30 AM** | **5. Freeze-Hour Observation**       | **Hands Off.** Engine discards truncated startup candle, records clean 3m candles, and locks `Base High` / `Base Low`.                  | Auto-rotates OTM strikes if LTP moves outside `₹4,000 – ₹5,500/lot` (with 15s cooldown).                                                                                            |
| **11:30 – 01:30 PM** | **6. Active Breakout Window**        | **Hands Off.** Enters `1` lot on confirmed 3m close `> Base High` with valid depth, spread `<= max(₹1.00, 0.5% of LTP)`, and `<= 5%` chase guard. | Automatically manages `1.5R` Cost-Adjusted BE, `2.5R` `+1R` Profit Lock, `+50%` 2-candle trail, `9 EMA` exit, and 1-candle Climax Wick.                                             |
| **01:30 PM**         | **7. Entry Cutoff**                  | If flat at `01:30 PM`, engine exits automatically (`[WINDOW CLOSED]`).                                                                  | If in a trade, continues managing until trailing exit or `03:15 PM` EOD square-off.                                                                                                 |
| **03:20 PM**         | **8. Post-Market Audit**             | `cat v3_paper_trades_log.csv`                                                                                                           | Verify closed trades, net P&L, and confirm zero open positions in OpenAlgo UI.                                                                                                      |

---

## Emergency `tmux` & Kill-Switch Commands

- **Reattach to running session:** `tmux attach -t algo_sess0`
- **Manual graceful stop:** Inside `tmux`, press `Ctrl+C` (triggers clean WebSocket unsubscribe & disconnect).
- **Crash recovery:** Restarting `python3 v3_momentum_engine.py` automatically reloads today's realized P&L and trade count from `v3_paper_trades_log.csv` so daily risk limits are never bypassed.
