"""
signal_engine/components.py

Each function computes one term of the signal formula, normalized to
roughly [-1, +1] (positive = bullish for the asset in question).
Every function returns None (not a fake neutral value) when it can't
honestly be computed from the given provider — the engine is
responsible for excluding None terms and renormalizing weights, never
for filling in a guess.
"""

import math
import statistics
from typing import Optional

from data_layer.providers.base import DataProvider

# Where we have a genuine futures counterpart to a spot/CFD instrument.
# Currently only Gold — everything else in our instrument list (majors
# FX, indices) has no distinct futures symbol in our current providers.
# Add entries here only once a provider can genuinely supply both legs.
FUTURES_COUNTERPART = {
    # "symbol_we_trade": "futures_symbol"
    # left empty on purpose: GOLD_FUT already IS the futures leg, and we
    # don't currently have a separate gold spot feed to compare it against.
}


def futures_momentum(provider: DataProvider, symbol: str,
                      lookback_periods: int = 10) -> Optional[float]:
    """Recent normalized price momentum. Positive = upward momentum."""
    try:
        history = provider.get_price_history(symbol, lookback_periods)
    except Exception:
        return None
    if len(history) < 2:
        return None
    start, end = history[0].price, history[-1].price
    if start == 0:
        return None
    pct_change = (end - start) / start
    # Squash into roughly [-1, 1] with a soft cap — a 2%+ move over the
    # lookback window saturates the signal rather than growing unbounded.
    return max(-1.0, min(1.0, pct_change / 0.02))


def order_flow(provider: DataProvider, symbol: str) -> Optional[float]:
    """No honest free data source currently exists for real order-flow
    imbalance. Returns None deliberately rather than approximating with
    volume — a volume-based proxy is a real design option but must be
    an explicit, separately-flagged choice, not silently substituted
    here. This is intentionally unimplemented."""
    return None


def lead_lag(provider: DataProvider, symbol: str,
              lookback_periods: int = 5) -> Optional[float]:
    """Compares recent futures-leg momentum against the spot/CFD leg's
    momentum. Only meaningful where we have both legs — see
    FUTURES_COUNTERPART above. Returns None when no counterpart exists,
    which today is every symbol we trade."""
    futures_symbol = FUTURES_COUNTERPART.get(symbol)
    if futures_symbol is None:
        return None
    spot_momentum = futures_momentum(provider, symbol, lookback_periods)
    fut_momentum = futures_momentum(provider, futures_symbol, lookback_periods)
    if spot_momentum is None or fut_momentum is None:
        return None
    divergence = fut_momentum - spot_momentum
    return max(-1.0, min(1.0, divergence))


def macro_confirmation(provider: DataProvider, symbol: str,
                        lookback_periods: int = 10) -> Optional[float]:
    """Uses DXY direction as a macro cross-check for USD-denominated
    pairs/instruments. A rising DXY is bearish confirmation for
    USD-quote pairs where USD is being bought (long USD), and the sign
    convention here assumes `symbol`'s momentum should typically move
    opposite to DXY for non-USD-base pairs. This is a simplification —
    treat it as a coarse macro cross-check, not a precise model."""
    dxy_momentum = futures_momentum(provider, "DXY", lookback_periods)
    if dxy_momentum is None:
        return None
    # For pairs quoted as XXXUSD (e.g. EURUSD), USD strength (DXY up)
    # should push the pair down — so macro confirmation for a LONG
    # signal on the pair is the negative of DXY momentum.
    # For USDXXX pairs (e.g. USDJPY, USDCAD) it's the opposite.
    usd_base_pairs = {"USDJPY", "USDCAD"}
    if symbol in usd_base_pairs:
        return max(-1.0, min(1.0, dxy_momentum))
    else:
        return max(-1.0, min(1.0, -dxy_momentum))


def volatility_risk(provider: DataProvider, symbol: str,
                     lookback_periods: int = 20) -> Optional[float]:
    """Realized volatility (stdev of returns) normalized against a
    reference level. Higher = more volatility risk = larger penalty."""
    try:
        history = provider.get_price_history(symbol, lookback_periods)
    except Exception:
        return None
    if len(history) < 3:
        return None
    prices = [p.price for p in history]
    returns = [(prices[i] - prices[i - 1]) / prices[i - 1]
               for i in range(1, len(prices)) if prices[i - 1] != 0]
    if len(returns) < 2:
        return None
    vol = statistics.pstdev(returns)
    # Reference: ~0.3% per-period stdev treated as "normal" for a daily
    # FX/index series; scale so ~3x that saturates the penalty at 1.0.
    reference = 0.003
    return max(0.0, min(1.0, vol / (reference * 3)))
