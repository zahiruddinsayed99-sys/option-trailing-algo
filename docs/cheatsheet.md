Yeh raha tumhara **Daily Pre-Market to Algo Launch Master Cheatsheet** (`09:00 AM – 11:30 AM IST`) — isko copy karke apne `~/trading-projects/option-trailing-algo/DAILY_LAUNCH_CHEATSHEET.md` file mein save kar lo taaki roz subah zero friction aur zero confusion ke saath 5 minute mein engine live ho jaaye!

---

### Daily Algo Launch Cheatsheet (`option-trailing-algo`)

| Time Window (IST) | Phase | Exact Action & Terminal Commands | Pass Criteria (Go / No-Go) |
| --- | --- | --- | --- |
| **09:00 – 09:15 AM** | **1. Infrastructure & Token Boot** | 1. Open WSL terminal & verify IST clock:<br>

<br>`date`<br>

<br>2. Start OpenAlgo gateway (if not running):<br>

<br>`cd ~/trading-projects/openalgo && source venv/bin/activate && python3 app.py`<br>

<br>3. Browser mein **`[http://127.0.0.1:5000](http://127.0.0.1:5000)`** kholo -> **Login with Fyers** (daily token refresh). | • `date` prints `IST 2026`<br>

<br>• OpenAlgo shows **Fyers Connected**<br>

<br>• Top bar is on **Analyze Mode** (Paper) |
| **09:15 – 10:15 AM** | **2. Macro & Direction Lock** | 1. No trades before 11:30 AM (observe opening volatility).<br>

<br>2. Check VIX, 15m index trend vs. VWAP, PCR/OI buildup, and top constituents volume (`>= 1.5x`).<br>

<br>3. Commit to **1 single bias (`CE` or `PE`)** for the day. | • Clear directional bias locked (`CE` OR `PE`, never both)<br>

<br>• If market is choppy/sideways -> **NO-TRADE DAY** |
| **10:15 – 10:25 AM** | **3. Strike Selection & Quote Test** | 1. Find active expiry strike priced in **₹220 – ₹320** range (fits `₹800` daily loss cap on 1 lot):<br>

<br>`cd ~/trading-projects/option-trailing-algo && source venv/bin/activate`<br>

<br>`python3 -c "from openalgo import api; import config; c=api(api_key=config.OPENALGO_API_KEY, host=config.OPENALGO_HOST); print(c.search(query='SENSEX 84100', exchange='BFO'))"`<br>

<br>2. Verify live feed & bid-ask spread (`<= ₹1.00`):<br>

<br>`python3 -c "from openalgo import api; import config; c=api(api_key=config.OPENALGO_API_KEY, host=config.OPENALGO_HOST); print(c.quotes(symbol='SENSEX26NOV2684100CE', exchange='BFO'))"` | • `status: success` with non-zero `ltp` & `volume`<br>

<br>• Bid-Ask spread `<= ₹1.00` (Index)<br>

<br>• Premium in `₹220–₹320` sweet spot |
| **10:25 – 10:29 AM** | **4. Config & Engine Launch** | 1. Update `SYMBOL`, `EXCHANGE`, `QTY` (`20` SENSEX / `65` NIFTY) in `config.py`.<br>

<br>2. Launch inside `tmux` so terminal close doesn't kill the bot:<br>

<br>`tmux new -s algo_session`<br>

<br>`cd ~/trading-projects/option-trailing-algo && source venv/bin/activate`<br>

<br>`python3 v3_momentum_engine.py` | • Engine prints `Trades: 0/3`<br>

<br>• Starts collecting `[FREEZE BASE #1...]` before `10:30 AM` |
| **10:30 – 11:30 AM** | **5. Freeze Hour (Hands Off)** | • Bot automatically records `Base High` and `Base Low` across 3-minute candles.<br>

<br>• Detach `tmux` safely anytime with `Ctrl+B` then `D` (`tmux attach -t algo_session` to view). | • At `11:30 AM`, terminal prints:<br>

<br>`>>> [11:30 BASE LOCKED] <<<` |
| **11:30 AM – 01:30 PM** | **6. Automated Execution Window** | • Bot enters only on 3m close `> Base High` AND risk `<= 13%`.<br>

<br>• Manages Stage 1 (`+25%` BE), Stage 2 (`+50%` 2-candle low trail), Stage 3 (`9 EMA`), Stage 4 (`2x` / climax wick), and `3:15 PM` EOD square-off. | • Zero manual overrides on SL or premature exits |
| **03:20 PM** | **7. EOD CSV Audit** | 1. Inspect today's trade log:<br>

<br>`cat v3_paper_trades_log.csv`<br>

<br>2. Paste CSV row + OpenAlgo Orderbook status in our chat for daily review. | • Audit tracked toward 15–20 paper-trade validation milestone |

---

### Quick Copy-Paste Command to Save This File in Your Repo

```bash
cd ~/trading-projects/option-trailing-algo
cat << 'EOF' > DAILY_LAUNCH_CHEATSHEET.md
# Daily Algo Launch Cheatsheet (09:00 AM – 03:20 PM IST)

## 1. 09:00 – 09:15 AM: Infrastructure & Daily Token Boot
- Check WSL IST Clock: `date`
- Start OpenAlgo (`~/trading-projects/openalgo`): `python3 app.py`
- Browser (`http://127.0.0.1:5000`): **Login with Fyers** (daily token refresh) & confirm **Analyze Mode**.

## 2. 09:15 – 10:15 AM: Macro Bias & Screening
- No trades before 11:30 AM.
- Check VIX, 15m index trend vs VWAP, OI/PCR buildup, and constituent volume (>= 1.5x).
- Lock 1 single direction (`CE` or `PE`).

## 3. 10:15 – 10:25 AM: Strike Lookup & Live Quote Check
- Search exact OpenAlgo symbol (`BFO` for SENSEX, `NFO` for NIFTY):
  `python3 -c "from openalgo import api; import config; c=api(api_key=config.OPENALGO_API_KEY, host=config.OPENALGO_HOST); print(c.search(query='SENSEX 84100', exchange='BFO'))"`
- Verify live LTP, volume & spread (<= ₹1.00), picking a ₹220–₹320 strike:
  `python3 -c "from openalgo import api; import config; c=api(api_key=config.OPENALGO_API_KEY, host=config.OPENALGO_HOST); print(c.quotes(symbol='SENSEX26NOV2684100CE', exchange='BFO'))"`

## 4. 10:25 – 10:29 AM: Update `config.py` & Launch in `tmux`
- Set `SYMBOL`, `EXCHANGE`, `QTY` (`20` SENSEX / `65` NIFTY) in `config.py`.
- Launch inside `tmux`:
  `tmux new -s algo_session`
  `cd ~/trading-projects/option-trailing-algo && source venv/bin/activate && python3 v3_momentum_engine.py`

## 5. 10:30 – 11:30 AM: Freeze Hour & 11:30 AM – 01:30 PM: Execution
- Hands off! Let the engine lock `[11:30 BASE LOCKED]` and manage all stages automatically.

## 6. 03:20 PM: EOD Audit
- Check log: `cat v3_paper_trades_log.csv`
- Share CSV + OpenAlgo Tradebook status for daily review.
EOF

```

*(Note: Abhi **11:16 AM** ho rahe hain — tumhara engine live chal raha hai aur **14 minutes** mein `11:30 BASE LOCKED` trigger hoga!)*