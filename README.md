# XAUUSD Candlestick Pattern Scanner

A desktop application (Tkinter GUI) that connects to a running **MetaTrader 5**
terminal, pulls live OHLC candles for **XAUUSDb** (Gold), scans them for classic
candlestick reversal/continuation patterns, and displays results as an
annotated candlestick chart plus a sortable signal table. Read-only — it never
places, modifies, or closes trades.

---

## 1. What's in this project

| File                     | Purpose                                                                 |
|---------------------------|--------------------------------------------------------------------------|
| `candlestick_patterns.py` | Pure pandas/numpy pattern-detection engine (no TA-Lib dependency)       |
| `mt5_data.py`              | Thin wrapper around the `MetaTrader5` package: connect + fetch candles |
| `gui_app.py`               | Tkinter GUI: controls, embedded matplotlib chart, signal table         |
| `test_patterns.py`         | Sanity tests with hand-crafted candle sequences                        |
| `requirements.txt`         | Python dependencies                                                    |

---

## 2. Requirements

- **Windows OS** — the `MetaTrader5` Python package only works on Windows,
  because it talks to a locally installed MT5 terminal via its native API.
  (The pattern engine and GUI logic themselves are OS-agnostic; only live
  data fetching needs Windows + MT5.)
- Python 3.10+
- A MetaTrader 5 terminal installed and **logged in** to a broker account
  that lists Gold, typically as `XAUUSDb`, `XAUUSD`, `XAUUSD.a`, or `GOLD`
  depending on the broker's suffix convention.

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## 3. Running the app

1. Open your MT5 terminal and log in to your account (demo or live).
2. Make sure the Gold symbol is visible in **Market Watch** (right-click →
   "Show All" if you don't see it).
3. Run:

   ```bash
   python gui_app.py
   ```

4. In the app:
   - Confirm/edit the **Symbol** field (default `XAUUSDb`).
   - Pick a **Timeframe** (M1 / M5 / M15 / M30 / H1 / H4 / D1).
   - Pick how many **Candles** to pull (default 200).
   - Click **Connect to MT5** — the status dot turns green when attached.
   - Click **Fetch & Scan** — this pulls fresh candles and re-runs the
     pattern scan. The chart and the signal table update together.
   - Optionally enable **Auto-refresh (30s)** to keep scanning on a timer.
   - Click **Export CSV** to save all detected signals to a file.
   - Click **Demo Data** any time (even without MT5 connected) to generate
     a synthetic random-walk candle series — useful for trying out the UI
     or for demoing the tool on non-Windows machines.

### If your broker's Gold symbol isn't exactly "XAUUSDb"

`mt5_data.resolve_symbol()` first tries the exact name you typed. If that
fails, it searches all symbols containing "XAU" or "GOLD" and raises an
error listing the close matches it found, so you know exactly what to type
into the Symbol field instead.

---

## 4. Patterns detected

| Pattern              | Type        | Candles | Bias      | Meaning (short)                                              |
|-----------------------|-------------|:-------:|-----------|----------------------------------------------------------------|
| Doji                  | Single      | 1       | Neutral   | Open ≈ close → indecision                                     |
| Hammer                | Single      | 1       | Bullish   | Small body top of range, long lower wick, after a downtrend   |
| Hanging Man            | Single      | 1       | Bearish   | Same shape as Hammer, but after an uptrend                    |
| Inverted Hammer        | Single      | 1       | Bullish   | Small body bottom of range, long upper wick, after a downtrend|
| Shooting Star          | Single      | 1       | Bearish   | Same shape as Inverted Hammer, but after an uptrend            |
| Marubozu               | Single      | 1       | Neutral   | Full body, negligible wicks → strong conviction                |
| Spinning Top           | Single      | 1       | Neutral   | Small body, wicks on both sides → indecision                   |
| Bullish Engulfing      | Two         | 2       | Bullish   | Bearish candle fully engulfed by a larger bullish candle       |
| Bearish Engulfing      | Two         | 2       | Bearish   | Bullish candle fully engulfed by a larger bearish candle       |
| Piercing Line          | Two         | 2       | Bullish   | Gap-down open, closes above midpoint of prior red body         |
| Dark Cloud Cover       | Two         | 2       | Bearish   | Gap-up open, closes below midpoint of prior green body         |
| Tweezer Top            | Two         | 2       | Bearish   | Two candles sharing the same high → resistance rejection       |
| Tweezer Bottom         | Two         | 2       | Bullish   | Two candles sharing the same low → support rejection           |
| Morning Star           | Three       | 3       | Bullish   | Bearish → small star → strong bullish, closing into first body |
| Evening Star           | Three       | 3       | Bearish   | Bullish → small star → strong bearish, closing into first body |
| Three White Soldiers   | Three       | 3       | Bullish   | Three consecutive rising bullish candles, solid bodies         |
| Three Black Crows      | Three       | 3       | Bearish   | Three consecutive falling bearish candles, solid bodies        |

**Trend context**: Hammer/Hanging Man and Inverted Hammer/Shooting Star are
geometrically identical — what makes them bullish vs. bearish is the trend
they appear in. The engine classifies trend with the slope of a short
(5-period, configurable) simple moving average of closes and only labels
a shape as one pattern or its bearish/bullish twin once that context
matches.

---

## 5. How detection works (engine design)

`candlestick_patterns.py` has three layers:

1. **Geometry helpers** — body size, full range, upper/lower wick length,
   body-to-range ratio, and a rolling average body size. Every pattern rule
   is built from these primitives instead of magic numbers scattered
   around, so thresholds are easy to find and retune in one place.

2. **Pattern functions** — one function per pattern (e.g. `hammer()`,
   `bullish_engulfing()`, `morning_star()`), each returning a boolean
   `pandas.Series` aligned to your OHLC DataFrame's index. For multi-candle
   patterns, the flag is set on the index of the **last** candle in the
   pattern.

3. **`detect_all(df)`** — runs every pattern in `PATTERN_REGISTRY`, applies
   trend-context filtering where needed, and returns a tidy DataFrame:

   ```
   time                pattern             bias      close
   2026-07-29 14:15:00 Bullish Engulfing   bullish   2407.00
   2026-07-29 15:00:00 Doji                neutral   2401.20
   ```

This engine works on **any** OHLC DataFrame (columns `open, high, low,
close`) — it isn't tied to MT5 specifically. You can feed it data from a
CSV, another broker API, or backtest data just as easily.

### Tuning thresholds

Every detector function takes its magic numbers as named parameters with
sane defaults (e.g. `doji(df, body_ratio_max=0.07)`), or as module-level
constants inline. Gold trades with much wider absolute ranges than most FX
pairs, so the defaults use **ratios** (body-to-range, wick-to-body)
rather than fixed price distances — this keeps the same thresholds sane
whether gold is at 2400 or 3200, and across timeframes from M1 to D1.

---

## 6. Extending the tool

- **Add a new pattern**: write a function `my_pattern(df) -> pd.Series`
  in `candlestick_patterns.py` following the existing style, then add it
  to `PATTERN_REGISTRY` with a bias and minimum candle count.
- **Change the symbol**: just type a different value into the Symbol
  field in the GUI (e.g. `XAUUSD`, `GOLD#`, `XAUUSD.a`) — no code changes
  needed as long as it's a valid symbol name on your broker.
- **Alerting**: `detect_all()` returns a plain DataFrame, so you can hook
  a sound alert, Telegram/Discord webhook, or MT5 push notification
  wherever `_render_table()` is called in `gui_app.py`, right after new
  signals come in.
- **Backtesting**: since the engine is decoupled from MT5, you can loop
  `detect_all()` over historical windows and compare pattern occurrence
  to forward returns to see which patterns actually have edge on XAUUSD
  at your chosen timeframe, before trusting any of them live.

---

## 7. Limitations & honest caveats

- Candlestick patterns are **descriptive shapes**, not proven predictive
  signals. Published win-rate stats for these patterns are mixed and
  vary a lot by market, timeframe, and regime. Treat detections as
  context/confluence, not standalone entry signals.
- The trend classifier (`_trend()`) is a simple SMA-slope heuristic. It's
  intentionally simple so it's easy to audit and retune — swap in ATR,
  ADX, or a longer/shorter window if you want a stricter trend filter.
- This tool does **not** execute trades, size positions, or manage risk.
  It's a read-only scanner intended to support your own discretionary or
  systematic decision-making — pair it with your own risk rules.
- MT5's `copy_rates_from_pos` returns candles as seen by your broker's
  server; times are in the broker's server timezone, not necessarily UTC
  or your local time. Check your broker's server time offset if you're
  aligning this with other data sources.
