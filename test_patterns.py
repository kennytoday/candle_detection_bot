"""Sanity tests: build hand-crafted OHLC sequences with KNOWN patterns and
confirm the detector fires on the expected candle."""
import pandas as pd
from candlestick_patterns import detect_all

rows = []
def add(o, h, l, c):
    rows.append({"open": o, "high": h, "low": l, "close": c})

# Padding candles to establish a clear downtrend (for hammer context)
for px in [2400, 2395, 2390, 2385, 2380]:
    add(px + 1, px + 2, px - 2, px - 1)  # small bearish candles, falling

# Hammer: small body near top, long lower wick
add(2378, 2379, 2368, 2378.5)

# Reset uptrend padding (for hanging man / shooting star context)
for px in [2380, 2385, 2390, 2395, 2400]:
    add(px - 1, px + 2, px - 2, px + 1)  # small bullish candles, rising

# Hanging man: same shape as hammer, now after uptrend
add(2401, 2402, 2391, 2401.5)

# Bullish engulfing pair
add(2400, 2401, 2395, 2396)   # bearish
add(2395, 2408, 2394, 2407)   # bullish, engulfs

# Bearish engulfing pair
add(2407, 2415, 2406, 2414)   # bullish
add(2415, 2416, 2400, 2401)   # bearish, engulfs

# Doji
add(2401, 2406, 2396, 2401.2)

# Marubozu (strong bullish, negligible wicks)
add(2401, 2430, 2400.5, 2429.5)

df = pd.DataFrame(rows)
df.index = pd.date_range("2026-07-01", periods=len(df), freq="1h")

signals = detect_all(df)
print(signals.to_string(index=False))
print(f"\nTotal signals detected: {len(signals)}")
assert not signals.empty, "No signals detected at all -- something is broken"
