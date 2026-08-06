"""
mt5_data.py
-----------
Thin wrapper around the MetaTrader5 Python package for connecting to a
running MT5 terminal and pulling OHLC candle data for a symbol
(default: XAUUSDb -- the common broker suffix "b" for gold CFDs on
cent/discount account types; change SYMBOL if your broker lists it
differently, e.g. "XAUUSD", "XAUUSD.a", "GOLD").

This module deliberately does NOT place trades. It is read-only market
data access for pattern-recognition/analysis purposes.

Requires:
    pip install MetaTrader5
    A running, logged-in MetaTrader 5 terminal on Windows
    (the MetaTrader5 package only works on Windows, since it talks to
    the local terminal via its native API).
"""

from __future__ import annotations
import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover - only fails on non-Windows / missing pkg
    mt5 = None


TIMEFRAME_MAP = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}


class MT5ConnectionError(RuntimeError):
    pass


def ensure_mt5_available() -> None:
    if mt5 is None:
        raise MT5ConnectionError(
            "The 'MetaTrader5' package is not installed or not available on "
            "this OS. Run: pip install MetaTrader5  (Windows only, requires "
            "a local MT5 terminal installation)."
        )


def connect(login: int | None = None, password: str | None = None,
            server: str | None = None, terminal_path: str | None = None) -> None:
    """
    Initialize the MT5 connection.

    If the terminal is already running and logged in to the desired
    account, you can call connect() with no arguments and it will
    attach to that session. Pass login/password/server explicitly to
    have the package log in to a specific account.
    """
    ensure_mt5_available()

    kwargs = {}
    if terminal_path:
        kwargs["path"] = terminal_path

    if not mt5.initialize(**kwargs):
        raise MT5ConnectionError(f"mt5.initialize() failed: {mt5.last_error()}")

    if login and password and server:
        authorized = mt5.login(login=login, password=password, server=server)
        if not authorized:
            raise MT5ConnectionError(f"mt5.login() failed: {mt5.last_error()}")


def disconnect() -> None:
    if mt5 is not None:
        mt5.shutdown()


def resolve_symbol(preferred: str) -> str:
    """
    Confirm `preferred` (e.g. 'XAUUSDb') exists in the broker's symbol list
    and is selected/visible in Market Watch. Falls back to a fuzzy search
    (e.g. 'XAUUSD', 'GOLD') if the exact name isn't found, and raises a
    clear error listing close matches if nothing usable is found.
    """
    ensure_mt5_available()

    info = mt5.symbol_info(preferred)
    if info is not None:
        if not info.visible:
            mt5.symbol_select(preferred, True)
        return preferred

    # Fuzzy fallback: search all symbols containing "XAU" or "GOLD"
    all_symbols = mt5.symbols_get()
    candidates = [s.name for s in all_symbols
                  if "XAU" in s.name.upper() or "GOLD" in s.name.upper()]
    if candidates:
        raise MT5ConnectionError(
            f"Symbol '{preferred}' not found on this broker. "
            f"Close matches available: {candidates[:10]}. "
            f"Update SYMBOL in the app to one of these."
        )
    raise MT5ConnectionError(
        f"Symbol '{preferred}' not found and no XAU/GOLD symbols exist "
        f"on this account."
    )


def fetch_ohlc(symbol: str, timeframe: str = "M15", n_candles: int = 300) -> pd.DataFrame:
    """
    Pull the most recent n_candles of OHLC data for `symbol` at `timeframe`.

    Returns a DataFrame indexed by UTC datetime with columns:
    open, high, low, close, tick_volume, spread, real_volume
    """
    ensure_mt5_available()

    if timeframe not in TIMEFRAME_MAP:
        raise ValueError(f"Unknown timeframe '{timeframe}'. Choose from {list(TIMEFRAME_MAP)}")

    tf_const = getattr(mt5, TIMEFRAME_MAP[timeframe])
    resolved_symbol = resolve_symbol(symbol)

    rates = mt5.copy_rates_from_pos(resolved_symbol, tf_const, 0, n_candles)
    if rates is None or len(rates) == 0:
        raise MT5ConnectionError(
            f"copy_rates_from_pos returned no data for {resolved_symbol}/{timeframe}. "
            f"Last error: {mt5.last_error()}"
        )

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.set_index("time")
    return df[["open", "high", "low", "close", "tick_volume", "spread", "real_volume"]]
