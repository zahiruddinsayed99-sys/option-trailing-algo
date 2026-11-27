Aaj (`feat/vwap-ema-confluence-auto` branch par) jo saare code changes aur logic upgrades kiye gaye hain, unka poora breakdown aur Monday se daily operate karne ka step-by-step runbook neeche diya gaya hai:

---

### 1. Aaj Kiye Gaye Exact Code Changes (File-by-File Summary)

- **`config.py` (Timing, % Risk Cap & Dynamic Daily Targets):**
- `OPTIONS_OBSERVE_START = "09:15"` aur `OPTIONS_WINDOW_START = "09:30"` kiya gaya (`1:30 PM` cutoff same hai) — 45-minute ka rigid Freeze Box wait hata diya gaya.
- Fixed `MAX_RISK_PER_TRADE = 500` ko hatakar **`MAX_SL_PCT = 0.25`** (trade value ka maximum `25%` SL), **`MAX_EMA_EXTENSION_PCT = 0.08`** (`9 EMA` se max `8%` doori tak entry), aur **`VOLUME_SURGE_MULT = 1.3`** (`1.3x` volume spike) add kiya gaya.
- `OPTIONS_DAILY_MAX_LOSS = -1200.0` kiya gaya taaki 1 full structural SL lagne par bhi system premature band na ho.
- `daily_targets.json` se aaj ke targets auto-load karne ke liye `DAILY_OPTIONS_LOADED` aur `DAILY_EQUITY_LOADED` flags alag-alag kiye gaye, plus `AUTO_START` support add hua.

- **`broker_adapter.py` (Spot Index Resolution & Fast Historical Hydration):**
- OpenAlgo SQLite database ke mutabik spot `SENSEX` ke liye **`BSE_INDEX`** aur `NIFTY` ke liye **`NSE_INDEX`** exchange mapping fix ki gayi (pehle `BSE`/`NSE` query hone se spot fallback ho raha tha).
- `sync_strike_indicators()` ke liye pichle din + aaj ke 3-minute candles fetch karke `<1 second` mein **Session VWAP, 9 EMA, 21 EMA, aur 20-period Volume SMA** calculate karne ka logic add kiya gaya.

- **`v3_momentum_engine.py` (Confluence Entry, 25% Structural SL & Staged Trailing):**
- **Upfront 4-Strike WebSocket Subscription:** Startup par hi `CANDIDATE_STRIKES` ke chaaro strikes WebSocket par subscribe hote hain taaki OTM rotation mein zero REST call aur zero `429` delay ho.
- **Incomplete Candle Dedup:** Mid-candle startup ya OTM rotation par agar REST history mein abhi chal rahi incomplete 3-minute candle aati hai, toh use drop karke sirf closed candles par EMA/VWAP calculate kiya jaata hai.
- **VWAP + EMA + Volume Confluence Entry:** Freeze Box High breakout ki jagah 5 live technical conditions lagayi gayi hain, aur OTM rotation ke baad `9 EMA` pullback continuation entries automatically allow hoti hain.
- **Percentage-Based Structural SL + R-Scaled Trailing:** `25%` max SL cap + `1.5R` Breakeven + `+50%` surge / `2.0R` par `+25%` floor lock + `9 EMA` / `2-candle low` trail implement kiya gaya.
- **`--auto` CLI Flag:** Interactive `input()` confirmation prompts bypass kiye gaye taaki `tmux` mein hands-free start ho sake.

- **`strike_screener.py` & `equity_screener.py` (Live Quote Verification):**
- Spot index lookup (`BSE_INDEX` / `NSE_INDEX`) fix kiya gaya aur explicit `live_quotes_ok` / `valid_quotes` count return kiya gaya taaki timeout ya `ltp=0` par fake fallback na ho.

- **`morning_launch.py` (One-Command Morning Orchestrator + Abort Guard):**
- Ek hi script dono screeners chalati hai (`1.5s` pacing gap ke saath taaki `multiquotes` collide na kare), `daily_targets.json` likhti hai, aur `tmux` session `algo_sess0` mein engines `--auto` mode mein start karti hai (`equity` tabhi start hoga jab Sensex-30 breadth `±0.30%` se zyada trending ho).
- **Broker Auth Abort Guard:** Agar OpenAlgo/Fyers logged-in nahi hai aur `0` live quotes milte hain, toh `daily_targets.json` likhne aur `tmux` launch karne se pehle `[ABORT]` error dekar ruk jaata hai.

- **`status.sh` & Cleanup:**
- Executable `status.sh` banayi gayi jo bina `tmux` khole 1 line mein OpenAlgo status, active `tmux` windows, aur aaj ke Options/Equity P&L dikhati hai. Purani unused `strategy_engine.py` ko `archive/` mein move kiya gaya.

---

### 2. Naya Business Logic & Live Execution Flow

| Stage                                         | Naya Business Rule                                                                                                                                      | Kyon & Kaise Kaam Karta Hai                                                                                                                       |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| **1. Morning Prep (`9:20–9:25 AM`)**          | `morning_launch.py` auto-selects sweet-spot strikes (`₹4,000–₹5,500/lot` non-expiry; `₹1,500–₹2,500/lot` expiry) & checks Sensex-30 breadth (`±0.30%`). | Agar broker session logged-in nahi hai toh `[ABORT]` karke safe rok deta hai; warna `daily_targets.json` save karke `algo_sess0` start karta hai. |
| **2. Instant Warm-Up (`< 2 sec`)**            | Prior-day + today's closed 3m candles hydrate hote hain; chaaro `CANDIDATE_STRIKES` WebSocket par subscribe hote hain.                                  | Pehle ki tarah 45-minute Freeze Box ka wait nahi karna padta—`9:30 AM` (ya `10:00 AM`) se hi `10:33 AM` jaisi early breakouts catch hoti hain.    |
| **3. Entry Confluence (`9:30 AM – 1:30 PM`)** | Closed 3m candle par **5 conditions** match honi chahiye:<br>                                                                                           |

<br>1. `Close > Session_VWAP`<br>

<br>2. `9_EMA > 21_EMA` aur `Close > 9_EMA`<br>

<br>3. `Volume >= 1.3x Vol_SMA_20`<br>

<br>4. `Close <= 9_EMA * 1.08` (Anti-Chase)<br>

<br>5. `Spread <= 0.5%` + valid depth | Extended spikes (`+15%` to `+25%` above 9 EMA) par chase block rehta hai; jab price wapas **9 EMA ke paas pullback** karke bounce karti hai tab clean entry milti hai. |
| **4. Initial Stop-Loss (`25%` Cap)** | `structural_sl = min(recent_3_candle_low, 21_EMA) - 0.50`<br>

<br>`pct_cap_sl = Entry * 0.75` (`25%` max risk)<br>

<br>`initial_sl = max(structural_sl, pct_cap_sl)` | Fixed `₹500` (`7.7 pts`) ki jagah option price ke hisaab se proportional breathing room milta hai (jaise `₹48` par `₹36` SL), jisse normal 3m red candle shakeout mein SL nahi katta. |
| **5. Staged Profit Riding (`₹48` $\rightarrow$ `₹75+`)** | • **`>= 1.5R` profit:** SL **Breakeven (`Entry + 0.30`)**<br>

<br>• **`>= +50%` gain ya `>= 2.0R`:** Min **`+25%` profit lock** (`Entry * 1.25`, with `+1R` bridge)<br>

<br>• **Trailing:** `max(locked_floor, min(prev_2_candle_low, 9_EMA - 1.50))` + climax-wick guard | `1.5R` ke baad loss ka risk zero ho jaata hai, aur `2-candle low` + `9 EMA - 1.50` buffer ke kaaran chhote 1-candle dips mein exit hue bina poori rally ride hoti hai. |
| **6. Re-Entry & Kill-Switches** | Trade exit hone par engine wapas `SCANNING` mode mein aata hai (ya price `> ₹85` ho toh OTM rotate karta hai). | Sirf 3 conditions par rukega: **Daily Loss `<= -₹1,200**`, **`MAX_TRADES_PER_DAY` poori**, ya **`1:30 PM` cutoff** (`3:15 PM` hard MIS square-off). |

---

### 3. Daily Operate Karne Ka Step-by-Step Runbook

#### A. Aaj Hi Kar Lein (Commit & Push on Feature Branch)

```bash
cd ~/trading-projects/option-trailing-algo
git status
git add -A
git commit -m "feat: VWAP+EMA+Vol confluence, 25% structural SL, morning_launch automation, and broker auth abort guard"
git push -u origin feat/vwap-ema-confluence-auto

```

#### B. Roz Subah Ka Routine (`9:20 – 9:25 AM` IST, ya `9:55 AM` IST)

1. **OpenAlgo Start & Broker Login:**

- `tmux` session `openalgo` mein OpenAlgo server chalu karein (agar pehle se chal raha hai toh check karein).
- Browser mein `[http://127.0.0.1:5000](http://127.0.0.1:5000)` khol kar **Fyers login** complete karein aur **`Analyze` (Paper-Trading) Mode** verify karein.

2. **One-Command Morning Launch:**

```bash
cd ~/trading-projects/option-trailing-algo && source venv/bin/activate && python morning_launch.py

```

- Yeh automatically screener chalayega, `daily_targets.json` update karega, aur `algo_sess0` mein Options (aur trending din par Equity) engine `--auto` mode mein start kar dega.

3. **Hands-Free Monitoring (Bina `tmux` Attach Kiye):**
   Jab bhi status ya P&L dekhna ho, kisi bhi terminal mein bas yeh chalayein:

```bash
cd ~/trading-projects/option-trailing-algo && ./status.sh

```

_(Live logs dekhne ho toh `tmux attach -t algo_sess0`, aur bahar nikalne ke liye `Ctrl+B` dabakar `D` dabayein.)_ 4. **End-of-Day & Merge to `dev` (Monday Session Ke Baad):**
Monday ke live paper-trading logs verify karne ke baad feature branch ko `dev` mein merge kar dein:

```bash
cd ~/trading-projects/option-trailing-algo
git checkout dev
git merge --no-ff feat/vwap-ema-confluence-auto
git push origin dev

```
