Analyzed equity_intraday_engine.py:L1-713

Yahan dono engines (**Options Engine** aur **Equity Engine**) ka complete workflow, steps, aur trading logic Hinglish mein diya gaya hai:

---

### 1. Subah Ka Launch Flow ([morning_launch.py](file:///wsl.localhost/Ubuntu/home/zahsay/trading-projects/option-trailing-algo/morning_launch.py))

Sabse pehle `morning_launch.py` dono screeners ko run karke aaj ka trading plan banata hai:

1. **Equity Regime & Stock Screening:** [equity_screener.py](file:///wsl.localhost/Ubuntu/home/zahsay/trading-projects/option-trailing-algo/equity_screener.py) Sensex-30 stocks ka average % move nikalta hai (`BULLISH`, `BEARISH`, ya `SIDEWAYS`).
2. **Option Direction Decide Karna:**
   - Agar `--direction` manually nahi diya gaya hai, toh regime ke hisaab se option type pick hota hai:
     - `BULLISH` → `CE`
     - `BEARISH` → `PE`
     - `SIDEWAYS` → `avg_move_pct >= 0` par `CE`, warna `PE`
3. **Strike Screening & Dynamic Index Rotation:** [strike_screener.py](file:///wsl.localhost/Ubuntu/home/zahsay/trading-projects/option-trailing-algo/strike_screener.py) active index (`SENSEX` ya `NIFTY`) aur best 4 OTM strikes choose karta hai.
4. **JSON Save Karna:** Saare results `daily_targets.json` mein save hote hain (`underlying`, `exchange`, `qty`, `expiry`, `dte`, `candidate_strikes`, `equity.regime`, `equity.direction`, `equity.watchlist`). Jab koi bhi engine start hota hai, [config.py](file:///wsl.localhost/Ubuntu/home/zahsay/trading-projects/option-trailing-algo/config.py) ka `load_daily_targets()` aaj ki date match hone par yeh values auto-load kar leta hai.
5. **Tmux Auto-Launch (`algo_sess0`):**
   - **Window 0 (`options`):** [v3_momentum_engine.py](file:///wsl.localhost/Ubuntu/home/zahsay/trading-projects/option-trailing-algo/v3_momentum_engine.py) hamesha start hota hai.
   - **Window 1 (`equity`):** [equity_intraday_engine.py](file:///wsl.localhost/Ubuntu/home/zahsay/trading-projects/option-trailing-algo/equity_intraday_engine.py) **sirf tabhi** start hota hai jab market trending ho (`|avg_move_pct| > 0.30%`, regime `BULLISH`/`BEARISH` ho, aur kam se kam 1 stock filter pass kare). `SIDEWAYS` din par Equity engine skip ho jata hai.

---

### 2. Options Engine ([strike_screener.py](file:///wsl.localhost/Ubuntu/home/zahsay/trading-projects/option-trailing-algo/strike_screener.py) + [v3_momentum_engine.py](file:///wsl.localhost/Ubuntu/home/zahsay/trading-projects/option-trailing-algo/v3_momentum_engine.py))

#### Step A: Dynamic Index Rotation & Strike Screening

1. **Index Rotation (`MIN_DTE = 2`):**
   - `resolve_active_index()` OpenAlgo ke SQLite `symtoken` table se `SENSEX` (`BFO`) ki nearest expiry (`>= today`) check karta hai.
   - **Agar `SENSEX DTE >= 2`:** `SENSEX` (`BFO`, `BSE_INDEX`, Lot Size `20` DB se) select hota hai.
   - **Agar `SENSEX DTE < 2`** (Wednesday 1-DTE, Thursday 0-DTE, ya holiday pre-poned expiry): Engine automatically **`NIFTY` (`NFO`, `NSE_INDEX`, Lot Size `65` DB se)** par switch ho jata hai aur `NIFTY` ki nearest expiry pick karta hai jiska `DTE >= 2`.
2. **Capital-Normalized Strike Ladder:**
   - Spot price ke around 12 OTM strikes scan hote hain (SENSEX mein 100 pts step, NIFTY mein 50 pts step).
   - **Target Capital Band:** ₹4,000 – ₹5,500 per lot (`IS_EXPIRY_DAY=TRUE` par ₹1,500 – ₹2,500).
     - `SENSEX` (Lot 20): ~₹200 – ₹275 premium.
     - `NIFTY` (Lot 65): ~₹61.54 – ₹84.62 premium.
   - **Liquidity Filter:** Bid > 0, Ask > 0, aur `spread <= 0.5% of LTP` (`0.005 * LTP`) hona zaroori hai.
   - Pehla `"SWEET SPOT"` strike milte hi uske aage ke up to **4 strikes** ka ladder (`CANDIDATE_STRIKES`) save ho jata hai.

#### Step B: Execution Workflow & Time Windows

- **Observe Window (`09:15 – 09:30` IST):** Sirf 3-minute candles, Session VWAP, aur ticks collect hote hain; koi trade nahi lagta.
- **Entry Window (`09:30 – 13:30` IST):** Nayi entries sirf is window mein allow hoti hain.
- **EOD Square-Off (`15:15` IST):** Agar koi position open hai toh `15:15` par MIS market exit ho jata hai.
- **Startup Sync & Hydration:**
  - Engine chaaro `CANDIDATE_STRIKES` ko upfront WebSocket par subscribe karta hai (taaki strike rotate karte waqt REST rate limit / 429 na aaye).
  - Active strike ke pichle 4 din ki `3m` candles fetch karke **Session VWAP**, **9 EMA**, **21 EMA**, aur **20-period Volume SMA** hydrate karta hai. Startup ka pehla adhoora 3m bucket discard hota hai.

#### Step C: Dynamic OTM Strike Auto-Rotation

Har 15 second mein (jab trade open nahi ho):

- Agar active strike ka LTP `max_prem` (₹5,500 / qty) se upar nikal jaye, toh ladder ke **agle saste OTM strike** par shift hota hai (valid depth + spread <= 0.5% check ke saath).
- Agar LTP `min_prem` (₹4,000 / qty) se neeche gir jaye, toh **pichle mehenge strike** par wapas rotate hota hai.

#### Step D: Confluence Entry Logic (3-Minute Candle Close Par)

Entry (`BUY` Market MIS) tabhi trigger hoti hai jab **paancho conditions** ek saath true hon:

1. **VWAP Confluence:** `Close > Session VWAP`
2. **EMA Trend:** Kam se kam 21 candles hon, `9 EMA > 21 EMA`, aur `Close > 9 EMA`
3. **Volume Surge:** Current 3m candle volume `>= 1.3x` trailing 20-candle Volume SMA
4. **Anti-Chase / Extension Guard:** `Close <= 9 EMA * 1.08` (yani price 9 EMA se 8% se zyada door bhaga hua na ho)
5. **Liquidity / Spread Guard:** Valid depth ho aur `spread <= 0.5% of LTP`

#### Step E: Stop-Loss, Trailing & Exit Logic

- **Initial SL:** `max(min(last_3_candles_low, 21_EMA) - 0.50, entry_price * 0.75)` — yani structural low/21 EMA ke neeche, lekin maximum risk **25% (`MAX_SL_PCT = 0.25`)** par capped.
- **Stage 1 (`1.5R` Profit):** LTP `>= entry + 1.5 * R` hit hote hi SL **cost-adjusted breakeven** (`entry + 0.30`) par aa jata hai.
- **Stage 2 (`+50%` gain ya `2.0R` Profit):** Floor SL lock hota hai (target `+25%` above entry) aur har 3m candle close par trailing update hota hai:
  `trail = max(locked_floor, min(prev_2_candle_low, 9_EMA - 1.50))`
- **Hard Target (`2X`):** Agar LTP `>= 2.0 * entry_price` (+100% double) hit kare toh turant exit.
- **Climax Wick Protection:** Agar trade `+25%` se upar hai aur ek candle par bada shooting-star/upper-wick bane (`upper_wick >= 2x body` aur `>= 50% candle_range`), toh **sirf agli candle** ke liye exit arm hota hai — agar agli candle uske `low` ke neeche close ho toh `CLIMAX_WICK_EXIT` ho jata hai, warna disarm ho jata hai.
- **Safety Guards:**
  - **Dead-Feed Failsafe:** 10 lagatar quote failures par open position turant MARKET exit.
  - **Daily Kill-Switches:** Max `3` trades/day (`MAX_TRADES_PER_DAY`) ya Daily Net Loss `<= -₹1,200` (`OPTIONS_DAILY_MAX_LOSS`), charges `₹55/trade`. Restart par [v3_paper_trades_log.csv](file:///wsl.localhost/Ubuntu/home/zahsay/trading-projects/option-trailing-algo/v3_paper_trades_log.csv) se aaj ka P&L aur trade count recover hota hai.

---

### 3. Equity Engine ([equity_screener.py](file:///wsl.localhost/Ubuntu/home/zahsay/trading-projects/option-trailing-algo/equity_screener.py) + [equity_intraday_engine.py](file:///wsl.localhost/Ubuntu/home/zahsay/trading-projects/option-trailing-algo/equity_intraday_engine.py))

#### Step A: Sensex-30 Regime & Stock Selection ([equity_screener.py](file:///wsl.localhost/Ubuntu/home/zahsay/trading-projects/option-trailing-algo/equity_screener.py))

1. **Market Breadth Check:** Sensex-30 stocks (NSE par) ke live quotes fetch karke har stock ka `% change` vs `prev_close` nikala jata hai (min 15/30 valid quotes zaroori hain).
2. **Regime Verdict (`MARKET_TREND_THRESHOLD_PCT = 0.30%`):**
   - `avg_move >= +0.30%` → **`BULLISH` (`LONG`)**
   - `avg_move <= -0.30%` → **`BEARISH` (`SHORT`)**
   - `-0.30% < avg_move < +0.30%` → **`SIDEWAYS` (`NONE`)** → No trade / Stand down.
3. **Stock Filtering & Ranking (Top 3):**
   - Stock move `>= +0.80%` (LONG ke liye) ya `<= -0.80%` (SHORT ke liye) (`STOCK_MIN_MOVE_PCT = 0.80`).
   - Bid/Ask valid ho aur `spread <= 0.10%`.
   - Affordability cap: `LTP <= ₹25,000 / 5 = ₹5,000` (taaki kam se kam 5 shares aa sakein).
   - **Score:** `abs(pct_change) * max(RVOL, 0.5)` (jahan `RVOL` time-of-day normalized relative volume hai) ke hisaab se **Top 3 stocks** select hote hain.

#### Step B: Execution Workflow & Freeze Box

- **Hydration:** Watchlist ke har stock ki subah `09:15` se `3m` candles fetch karke **Session VWAP** aur **Freeze Box (`base_high`, `base_low`)** calculate hota hai.
- **Session Windows (IST):**
  - **Freeze Box (`10:15 – 11:00`):** Is dauran banne wali 3m candles ka highest high (`base_high`) aur lowest low (`base_low`) record hota hai.
  - **Entry Hunting (`11:00 – 13:30`):** Breakout/breakdown entries sirf is window mein hoti hain (ek time par max 1 active stock position).
  - **EOD Square-Off (`15:10`):** Open position `15:10` IST par close ho jati hai.

#### Step C: Breakout / Breakdown Entry Logic (3m Candle Close Par)

1. **Liquidity & Volume Filters:** Valid bid-ask depth, `spread <= 0.10%`, aur candle volume `>= 1.5x` rolling 10-candle average (`VOLUME_SURGE_MULTIPLIER = 1.5`).
2. **LONG Setup:**
   - `Close > base_high` **AND** `Close > Session VWAP`
   - **Chase Guard:** `Close <= base_high * 1.015` (max 1.5% extension allow)
3. **SHORT Setup:**
   - `Close < base_low` **AND** `Close < Session VWAP`
   - **Chase Guard:** `Close >= base_low * 0.985` (max 1.5% extension allow)
4. **Risk-Normalized Position Sizing:**
   - Structural SL = `base_low` (LONG) / `base_high` (SHORT), capped at max **0.8%** distance (`MAX_STRUCTURAL_STOP_PCT = 0.008`).
   - `Qty = min(₹400 // risk_per_share, ₹25,000 // Close)` (min 1 share) — yani har trade par max risk **₹400** aur max capital **₹25,000**.

#### Step D: Staged Trailing & Exit Logic

- **Stage 1 (`+1.5R`):** Price `1.5R` move karte hi SL **cost-adjusted breakeven** (`entry ± (₹35/qty + 0.05)`) par shift hota hai.
- **Stage 2 (`+2.5R`):** Price `2.5R` hit karte hi **`+1.0R` profit lock** ho jata hai, aur har 3m candle close par:
  - **2-Candle Swing Trail:** SL last 2 candles ke low (LONG) / high (SHORT) par tighten hota hai.
  - **9 EMA Break Exit:** Agar 3m candle `9 EMA` ke opposite side close ho (`Close < 9 EMA` LONG mein, `Close > 9 EMA` SHORT mein) toh turant exit (`9EMA_BREAK`).
- **Hard Target (`+4.0R`):** Tick par `4.0R` hit hote hi immediate exit (`HARD_TARGET_4R`).
- **Safety Guards:**
  - **Dead-Feed Failsafe:** 10 consecutive quote failures par immediate MARKET exit (`FAILSAFE_DEAD_FEED`).
  - **Daily Kill-Switches:** Max `2` trades/day (`EQUITY_MAX_TRADES_PER_DAY`) ya Daily Net Loss `<= -₹800` (`EQUITY_MAX_DAILY_LOSS`), charges `₹35/trade`. Data [equity_paper_trades_log.csv](file:///wsl.localhost/Ubuntu/home/zahsay/trading-projects/option-trailing-algo/equity_paper_trades_log.csv) mein log aur recover hota hai.

---

### 4. Daily Run Commands (Quick Reference)

- **Normal Morning Launch (Auto Index Rotation + Tmux):**
  ```bash
  python3 morning_launch.py --attach
  ```
- **Dry-Run Check (Sirf Screening + `daily_targets.json` check karne ke liye):**
  ```bash
  python3 morning_launch.py --dry-run
  ```
- **Status Check:**
  ```bash
  ./status.sh
  ```
