"""
candlestick_patterns.py
------------------------
Pure pandas/numpy candlestick pattern recognition engine.

No TA-Lib dependency required — every pattern is detected from raw
OHLC values using standard candlestick-analysis rules of thumb, tuned
with tolerances suitable for XAUUSD (gold), which is a high-volatility,
wide-range instrument compared to most FX pairs.

Every detector function:
    * takes a pandas DataFrame with columns: open, high, low, close
      (datetime index optional but recommended)
    * returns a boolean pandas Series aligned to the DataFrame index,
      True where the pattern is detected on that candle (for
      multi-candle patterns, True is set on the LAST candle of the
      pattern).

detect_all() runs every detector and returns a tidy "signals" DataFrame
with one row per detected pattern occurrence, ready to hand to a GUI,
CSV export, or a trading rule engine.
"""

from __future__ import annotations
import numpy as np
import pandas as pd


# --------------------------------------------------------------------------
# Low-level candle geometry helpers
# --------------------------------------------------------------------------

def _body(df: pd.DataFrame) -> pd.Series:
    """Absolute size of the candle body (open-close distance)."""
    return (df["close"] - df["open"]).abs()


def _range(df: pd.DataFrame) -> pd.Series:
    """Full high-low range of the candle. Tiny epsilon avoids /0 on flat bars."""
    return (df["high"] - df["low"]).replace(0, np.nan)


def _upper_wick(df: pd.DataFrame) -> pd.Series:
    return df["high"] - df[["open", "close"]].max(axis=1)


def _lower_wick(df: pd.DataFrame) -> pd.Series:
    return df[["open", "close"]].min(axis=1) - df["low"]


def _is_bullish(df: pd.DataFrame) -> pd.Series:
    return df["close"] > df["open"]


def _is_bearish(df: pd.DataFrame) -> pd.Series:
    return df["close"] < df["open"]


def _body_ratio(df: pd.DataFrame) -> pd.Series:
    """Body size as a fraction of the full candle range, in [0, 1]."""
    return (_body(df) / _range(df)).clip(0, 1)


def _avg_body(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Rolling average body size, used to classify 'small' vs 'large' bodies."""
    return _body(df).rolling(window, min_periods=1).mean()


# --------------------------------------------------------------------------
# Single-candle patterns
# --------------------------------------------------------------------------

def doji(df: pd.DataFrame, body_ratio_max: float = 0.07) -> pd.Series:
    """
    Doji: open and close are almost identical -> indecision candle.
    body_ratio_max controls how strict the "almost identical" test is.
    """
    return _body_ratio(df) <= body_ratio_max


def hammer(df: pd.DataFrame) -> pd.Series:
    """
    Hammer: small body near the TOP of the range, long lower wick
    (>= 2x body), little/no upper wick. Bullish reversal signal when
    it appears after a downtrend (trend context is added in detect_all).
    """
    body = _body(df)
    lower = _lower_wick(df)
    upper = _upper_wick(df)
    small_body = _body_ratio(df) <= 0.35
    long_lower = lower >= 2 * body.replace(0, np.nan)
    small_upper = upper <= body * 0.5 + 1e-9
    return small_body & long_lower & small_upper


def inverted_hammer(df: pd.DataFrame) -> pd.Series:
    """Small body near the BOTTOM of the range, long upper wick. Potential bullish reversal."""
    body = _body(df)
    lower = _lower_wick(df)
    upper = _upper_wick(df)
    small_body = _body_ratio(df) <= 0.35
    long_upper = upper >= 2 * body.replace(0, np.nan)
    small_lower = lower <= body * 0.5 + 1e-9
    return small_body & long_upper & small_lower


def hanging_man(df: pd.DataFrame) -> pd.Series:
    """
    Geometrically identical to a Hammer, but bearish in meaning because
    context matters: it must appear after an UPTREND. We reuse the shape
    test here; trend filtering happens in detect_all().
    """
    return hammer(df)


def shooting_star(df: pd.DataFrame) -> pd.Series:
    """
    Geometrically identical to an Inverted Hammer, but bearish because it
    appears after an UPTREND. Shape test reused; trend filtering in detect_all().
    """
    return inverted_hammer(df)


def marubozu(df: pd.DataFrame, wick_max_ratio: float = 0.05) -> pd.Series:
    """Marubozu: (near) full-body candle with negligible wicks on both ends -> strong conviction."""
    rng = _range(df)
    upper = _upper_wick(df) / rng
    lower = _lower_wick(df) / rng
    strong_body = _body_ratio(df) >= 0.9
    return strong_body & (upper <= wick_max_ratio) & (lower <= wick_max_ratio)


def spinning_top(df: pd.DataFrame) -> pd.Series:
    """Small real body with wicks on both sides roughly similar in length -> indecision."""
    body = _body(df)
    upper = _upper_wick(df)
    lower = _lower_wick(df)
    small_body = _body_ratio(df) <= 0.3
    has_both_wicks = (upper > body * 0.5) & (lower > body * 0.5)
    return small_body & has_both_wicks & ~doji(df)


# --------------------------------------------------------------------------
# Two-candle patterns
# --------------------------------------------------------------------------

def bullish_engulfing(df: pd.DataFrame) -> pd.Series:
    """Prior bearish candle fully engulfed by a larger bullish candle's body."""
    o, c = df["open"], df["close"]
    prev_o, prev_c = o.shift(1), c.shift(1)
    prev_bearish = prev_c < prev_o
    curr_bullish = c > o
    engulfs = (o <= prev_c) & (c >= prev_o)
    return prev_bearish & curr_bullish & engulfs


def bearish_engulfing(df: pd.DataFrame) -> pd.Series:
    """Prior bullish candle fully engulfed by a larger bearish candle's body."""
    o, c = df["open"], df["close"]
    prev_o, prev_c = o.shift(1), c.shift(1)
    prev_bullish = prev_c > prev_o
    curr_bearish = c < o
    engulfs = (o >= prev_c) & (c <= prev_o)
    return prev_bullish & curr_bearish & engulfs


def piercing_line(df: pd.DataFrame) -> pd.Series:
    """
    Bearish candle followed by a bullish candle that opens below the prior
    low and closes above the midpoint of the prior candle's body.
    """
    o, c, low = df["open"], df["close"], df["low"]
    prev_o, prev_c = o.shift(1), c.shift(1)
    prev_mid = (prev_o + prev_c) / 2
    prev_bearish = prev_c < prev_o
    curr_bullish = c > o
    opens_below_low = o < df["low"].shift(1)
    closes_above_mid = c > prev_mid
    closes_below_prev_open = c < prev_o
    return prev_bearish & curr_bullish & opens_below_low & closes_above_mid & closes_below_prev_open


def dark_cloud_cover(df: pd.DataFrame) -> pd.Series:
    """
    Bullish candle followed by a bearish candle that opens above the prior
    high and closes below the midpoint of the prior candle's body.
    """
    o, c = df["open"], df["close"]
    prev_o, prev_c = o.shift(1), c.shift(1)
    prev_mid = (prev_o + prev_c) / 2
    prev_bullish = prev_c > prev_o
    curr_bearish = c < o
    opens_above_high = o > df["high"].shift(1)
    closes_below_mid = c < prev_mid
    closes_above_prev_open = c > prev_o
    return prev_bullish & curr_bearish & opens_above_high & closes_below_mid & closes_above_prev_open


def tweezer_top(df: pd.DataFrame, tol: float = 0.0008) -> pd.Series:
    """Two consecutive candles sharing (almost) the same high -> resistance rejection."""
    high = df["high"]
    prev_high = high.shift(1)
    close_enough = (high - prev_high).abs() <= tol * high
    prev_bullish = df["close"].shift(1) > df["open"].shift(1)
    curr_bearish = df["close"] < df["open"]
    return close_enough & prev_bullish & curr_bearish


def tweezer_bottom(df: pd.DataFrame, tol: float = 0.0008) -> pd.Series:
    """Two consecutive candles sharing (almost) the same low -> support rejection."""
    low = df["low"]
    prev_low = low.shift(1)
    close_enough = (low - prev_low).abs() <= tol * low
    prev_bearish = df["close"].shift(1) < df["open"].shift(1)
    curr_bullish = df["close"] > df["open"]
    return close_enough & prev_bearish & curr_bullish


# --------------------------------------------------------------------------
# Three-candle patterns
# --------------------------------------------------------------------------

def morning_star(df: pd.DataFrame) -> pd.Series:
    """
    Bearish candle -> small-bodied "star" candle (gaps down) -> bullish candle
    closing well into the first candle's body. Bullish reversal.
    """
    o, c = df["open"], df["close"]
    c1_bear = c.shift(2) < o.shift(2)
    star_small = _body_ratio(df.shift(1)) <= 0.35
    c3_bull = c > o
    c3_closes_deep = c > (o.shift(2) + c.shift(2)) / 2
    gap_down = df["high"].shift(1) < o.shift(2).combine(c.shift(2), min)
    return c1_bear & star_small & c3_bull & c3_closes_deep


def evening_star(df: pd.DataFrame) -> pd.Series:
    """
    Bullish candle -> small-bodied "star" candle (gaps up) -> bearish candle
    closing well into the first candle's body. Bearish reversal.
    """
    o, c = df["open"], df["close"]
    c1_bull = c.shift(2) > o.shift(2)
    star_small = _body_ratio(df.shift(1)) <= 0.35
    c3_bear = c < o
    c3_closes_deep = c < (o.shift(2) + c.shift(2)) / 2
    return c1_bull & star_small & c3_bear & c3_closes_deep


def three_white_soldiers(df: pd.DataFrame) -> pd.Series:
    """Three consecutive long bullish candles, each closing higher than the last, small wicks."""
    o, c = df["open"], df["close"]
    bull0 = c.shift(2) > o.shift(2)
    bull1 = c.shift(1) > o.shift(1)
    bull2 = c > o
    rising = (c.shift(1) > c.shift(2)) & (c > c.shift(1))
    opens_within_prev_body = (o.shift(1) > o.shift(2)) & (o.shift(1) < c.shift(2)) & \
                              (o > o.shift(1)) & (o < c.shift(1))
    solid_bodies = (_body_ratio(df) >= 0.5) & (_body_ratio(df.shift(1)) >= 0.5) & (_body_ratio(df.shift(2)) >= 0.5)
    return bull0 & bull1 & bull2 & rising & opens_within_prev_body & solid_bodies


def three_black_crows(df: pd.DataFrame) -> pd.Series:
    """Three consecutive long bearish candles, each closing lower than the last, small wicks."""
    o, c = df["open"], df["close"]
    bear0 = c.shift(2) < o.shift(2)
    bear1 = c.shift(1) < o.shift(1)
    bear2 = c < o
    falling = (c.shift(1) < c.shift(2)) & (c < c.shift(1))
    opens_within_prev_body = (o.shift(1) < o.shift(2)) & (o.shift(1) > c.shift(2)) & \
                              (o < o.shift(1)) & (o > c.shift(1))
    solid_bodies = (_body_ratio(df) >= 0.5) & (_body_ratio(df.shift(1)) >= 0.5) & (_body_ratio(df.shift(2)) >= 0.5)
    return bear0 & bear1 & bear2 & falling & opens_within_prev_body & solid_bodies


# --------------------------------------------------------------------------
# Trend context (needed to disambiguate Hammer/HangingMan, InvHammer/ShootingStar)
# --------------------------------------------------------------------------

def _trend(df: pd.DataFrame, window: int = 5) -> pd.Series:
    """
    Simple trend classifier based on the slope of a short SMA of closes.
    Returns a Series of 'up', 'down', or 'flat'.
    """
    sma = df["close"].rolling(window, min_periods=window).mean()
    slope = sma.diff()
    out = pd.Series("flat", index=df.index)
    out[slope > 0] = "up"
    out[slope < 0] = "down"
    return out


# --------------------------------------------------------------------------
# Registry + master detector
# --------------------------------------------------------------------------

# name -> (function, bias, min_candles_required)
# bias: 'bullish', 'bearish', or 'neutral' (context-dependent, refined below)
PATTERN_REGISTRY = {
    "Doji":               (doji, "neutral", 1),
    "Hammer":             (hammer, "bullish", 1),
    "Hanging Man":        (hanging_man, "bearish", 1),
    "Inverted Hammer":    (inverted_hammer, "bullish", 1),
    "Shooting Star":      (shooting_star, "bearish", 1),
    "Marubozu":           (marubozu, "neutral", 1),
    "Spinning Top":       (spinning_top, "neutral", 1),
    "Bullish Engulfing":  (bullish_engulfing, "bullish", 2),
    "Bearish Engulfing":  (bearish_engulfing, "bearish", 2),
    "Piercing Line":      (piercing_line, "bullish", 2),
    "Dark Cloud Cover":   (dark_cloud_cover, "bearish", 2),
    "Tweezer Top":        (tweezer_top, "bearish", 2),
    "Tweezer Bottom":     (tweezer_bottom, "bullish", 2),
    "Morning Star":       (morning_star, "bullish", 3),
    "Evening Star":       (evening_star, "bearish", 3),
    "Three White Soldiers": (three_white_soldiers, "bullish", 3),
    "Three Black Crows":  (three_black_crows, "bearish", 3),
}


def detect_all(df: pd.DataFrame, trend_window: int = 5) -> pd.DataFrame:
    """
    Run every registered pattern detector against df.

    Parameters
    ----------
    df : DataFrame with columns open, high, low, close (datetime index recommended)
    trend_window : SMA window used to disambiguate Hammer-vs-HangingMan and
                   InvertedHammer-vs-ShootingStar by prior trend direction.

    Returns
    -------
    DataFrame with columns: time, pattern, bias, close
    sorted by time, one row per detected occurrence.
    """
    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}")

    trend = _trend(df, trend_window)
    prior_trend = trend.shift(1)  # trend going INTO this candle

    rows = []
    for name, (func, bias, min_candles) in PATTERN_REGISTRY.items():
        try:
            mask = func(df)
        except Exception:
            # Defensive: never let one bad pattern crash the whole scan.
            continue
        mask = mask.fillna(False)

        # Context refinement for shape-ambiguous patterns.
        if name == "Hammer":
            mask = mask & (prior_trend == "down")
        elif name == "Hanging Man":
            mask = mask & (prior_trend == "up")
        elif name == "Inverted Hammer":
            mask = mask & (prior_trend == "down")
        elif name == "Shooting Star":
            mask = mask & (prior_trend == "up")

        idx = df.index[mask]
        for i in idx:
            rows.append({
                "time": i,
                "pattern": name,
                "bias": bias,
                "close": df.loc[i, "close"],
            })

    signals = pd.DataFrame(rows, columns=["time", "pattern", "bias", "close"])
    if not signals.empty:
        signals = signals.sort_values("time").reset_index(drop=True)
    return signals


def latest_signal(df: pd.DataFrame, lookback: int = 1) -> pd.DataFrame:
    """Convenience: return only patterns detected on the most recent `lookback` candles."""
    all_signals = detect_all(df)
    if all_signals.empty:
        return all_signals
    cutoff_index = df.index[-lookback:]
    return all_signals[all_signals["time"].isin(cutoff_index)]
