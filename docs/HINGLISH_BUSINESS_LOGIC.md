Yahan dono engines (**Options Momentum Engine V3.4** aur **NSE Cash Equity Intraday Engine V1.0**) ki **Business & Trading Logic** simple, beginner-friendly Hinglish mein samjhayi gayi hai — taaki aapko clear pata ho ki aapka system _kyun_ aur _kaise_ paisa banata hai aur loss ko kaise rokta hai.

---

### Core Philosophy: Dono Engines Ek Hi Formula Par Kaam Karte Hain

Retail traders ka sabse bada nuksan **morning noise (09:15–10:30 AM)** mein jaldi entry lene aur **bade losses ko hold karne** se hota hai. Aapke dono engines is problem ko 3 rules se solve karte hain:

1. **Wait for the Trap to Finish (10:30 – 11:30 AM Freeze Hour):** Subah ke pehle 1.25 ghante market ko apni direction decide karne dete hain. `10:30 se 11:30 AM` ke beech market jo range (**Base High – Base Low**) banata hai, usse hum apna **Launchpad Box** maante hain.
2. **Trade Only Confirmed Breakouts (11:30 AM – 01:30 PM):** Sirf jab 3-minute ki candle us box ke bahar **close** hoti hai (sirf wick nahi), tabhi entry milti hai.
3. **Fixed Rupee Risk + Smart Profit Locking:** Har trade mein maximum nuksan pehle se fixed hai (`₹500` Options mein, `₹400` Equity mein), lekin profit ke liye koi chhota target nahi — trailing stop-loss ke saath bade moves ko ride kiya jaata hai.

---

### Engine 1: Options Momentum Engine V3.4 (`v3_momentum_engine.py`)

**Business Goal:** Kam capital (`₹4,000 – ₹5,000` per lot) mein index ke sharp momentum move se `1.5x` se `2x` return nikalna, bina theta decay ya panic ke.

- **Sahi Option Kaise Chunta Hai? (`₹4K – ₹5K/lot` Capital Rule):**
- Chahe **SENSEX** (`20 qty`) ho ya **NIFTY** (`65 qty`), bot sirf wahi strike trade karta hai jiska 1 lot **`₹4,000 se ₹5,000`** ke beech aaye (`₹200–₹250` SENSEX par; `₹61.55–₹76.90` NIFTY par).
- **Fayda:** Is range ke options mein delta achha hota hai (price fast badhta hai) aur bid-ask spread tight rehta hai (`<= ₹1.00`). Agar premium mehenga ho jaaye toh bot khud agle OTM strike par shift ho jaata hai (**Auto-Rotation**).

- **Entry Kab Leta Hai?**
- `11:30 AM – 01:30 PM` ke beech jab 3-minute candle `Base High` ke upar close ho.
- **5% Chase Guard:** Agar ek hi candle mein option `5%` se zyada bhaag chuka hai, toh bot usme nahi kudta — mehenge bhaav par fassne se bachata hai.

- **Risk & Profit Locking Kaise Hota Hai? (4-Stage Safety Net):**
- **Initial Stop-Loss:** `Base Low` par, lekin maximum **`₹500` loss** (`25 pts` SENSEX / `7.7 pts` NIFTY) par capped.
- **Stage 1 (`1:1.5 R:R` par):** Jaise hi profit risk ka `1.5x` (`~₹750`) pahunchta hai, SL automatic **Entry + Charges (Cost Breakeven)** par aa jaata hai — ab trade mein loss impossible hai.
- **Stage 1.5 (`1:2.5 R:R` par):** Profit `2.5x` (`~₹1,250`) hote hi SL **`+1R` (`+₹500` guaranteed profit)** par lock ho jaata hai.
- **Stage 2 (`+50%` Surge par):** Option `50%` badhte hi SL **`+25%` profit** par lock hota hai aur pichhli 2 candles ke low (`2-Candle Trail`) aur `9 EMA` ke saath upar chalta rehta hai — jab tak momentum khatam na ho (`Climax Wick` ya `2x` target).

---

### Engine 2: NSE Cash Equity Intraday Engine V1.0 (`equity_intraday_engine.py`)

**Business Goal:** Bina option expiry/theta decay ke, market ki direction wale **Top 3 Heavyweight Stocks** mein high-probability intraday trend pakadna.

- **Stock Selection Logic (Market-Aligned Sensex 30 Scanner):**
- Bot andhadhun kisi bhi stock mein trade nahi karta. `11:25 AM` par pehle **SENSEX Index** ka mood check karta hai:
- Agar SENSEX **`+0.30%` ya zyada upar** hai $\rightarrow$ **BULLISH Day** $\rightarrow$ Sensex 30 ke **Top 3 Gainers** (`>= +0.80%` up) chunta hai aur sirf **BUY (`LONG`)** setups dhundhta hai.
- Agar SENSEX **`-0.30%` ya zyada niche** hai $\rightarrow$ **BEARISH Day** $\rightarrow$ Sensex 30 ke **Top 3 Losers** (`<= -0.80%` down) chunta hai aur sirf **SELL (`SHORT`)** setups dhundhta hai.
- Agar SENSEX **`-0.30%` se `+0.30%` ke beech** atka hai $\rightarrow$ **SIDEWAYS Day** $\rightarrow$ Koi trade nahi leta (chop market se bachav).

- **Entry Kab Leta Hai? (Double Confirmation):**
- **BUY (`LONG`):** 3m candle `Base High` ke upar close ho + Price **Session VWAP** ke upar ho (buyers control mein hain) + Volume pichhli 10 candles ke average se **`1.5x` zyada** ho (institutional volume surge).
- **SELL (`SHORT`):** 3m candle `Base Low` ke niche close ho + Price **Session VWAP** ke niche ho + **`1.5x` Volume Surge** ho.

- **Quantity & Risk Sizing (`₹400` Fixed Risk Formula):**
- Stock chahe `₹300` ka ho (`TATASTEEL`) ya `₹3,500` ka (`TCS`), har trade mein risk strictly **`₹400`** hi rehta hai:

$$\text{Qty} = \frac{₹400}{\text{Entry Price} - \text{Stop Loss}}$$

- Saath hi total order value **`₹25,000`** (`~₹5,000` MIS margin at 5x leverage) se upar nahi jaati.

- **Profit Locking & Exit:**
- Bilkul Options engine ki tarah **`1.5R` par Cost Breakeven**, **`2.5R` par `+1R` (`+₹400`) Profit Lock + 2-Candle Swing & `9 EMA` Trail**, **`4.0R` par Target Exit**, aur **`03:10 PM`** par automatic MIS square-off (broker penalty se pehle).

---

### Ek Nazar Mein Dono Engines Ka Comparison

| Parameter                | Options Momentum Engine (V3.4)             | Cash Equity Engine (V1.0)                     |
| ------------------------ | ------------------------------------------ | --------------------------------------------- |
| **Kya Trade Karta Hai?** | SENSEX / NIFTY Options (`CE` ya `PE`)      | Top 3 Trending Sensex-30 Stocks (`NSE` MIS)   |
| **Direction**            | Buying Only (`LONG` Option Premium)        | Both **`LONG` (Buy)** & **`SHORT` (Sell)**    |
| **Margin Required**      | `₹4,000 – ₹5,000` (1 Lot)                  | `~₹5,000` (`<= ₹25,000` MIS notional at 5x)   |
| **Max Risk / Trade**     | `₹500`                                     | `₹400`                                        |
| **Daily Kill-Switch**    | `-₹800` loss ya `3` trades/day             | `-₹800` loss ya `2` trades/day                |
| **Sabse Badi Taqat**     | Chhote capital par `50%–100%` fast returns | Zero theta decay + VWAP & Volume confirmation |

---
