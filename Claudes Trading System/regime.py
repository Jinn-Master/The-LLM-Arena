"""
signal_engine/regime.py

Classifies current market regime so the signal engine (and later, the
strategy layer) can decide which playbook applies — per the spec's
"TRENDING -> Momentum strategy ON / MEAN REVERTING -> Reversion
strategy ON / NEWS RISK -> all new positions off" logic.

NEWS_RISK is NOT implemented here. Detecting it needs an economic
calendar data source (e.g. ForexFactory, Investing.com calendar, or a
paid calendar API) which hasn't been decided yet — flagged the same
way as OrderFlow: this function will never silently report
NEWS_RISK=False when it actually has no idea. It raises rather than
guessing wrong in a way that could look like a real check.
"""

import statistics
from dataclasses import dataclass
from enum import Enum
from typing import List

from data_layer.providers.base import DataProvider


class Regime(Enum):
    TRENDING = "trending"
    MEAN_REVERTING = "mean_reverting"
    HIGH_VOLATILITY = "high_volatility"
    LOW_LIQUIDITY = "low_liquidity"
    UNKNOWN = "unknown"  # insufficient data to classify — never silently
                         # defaults to a specific regime


@dataclass
class RegimeReading:
    regime: Regime
    trend_strength: float      # 0-1, higher = stronger directional trend
    volatility_level: float    # 0-1, higher = more volatile than normal
    confidence: float          # 0-1, how much data supported this read


def detect_regime(provider: DataProvider, symbol: str,
                   lookback_periods: int = 20) -> RegimeReading:
    try:
        history = provider.get_price_history(symbol, lookback_periods)
    except Exception:
        return RegimeReading(Regime.UNKNOWN, 0.0, 0.0, 0.0)

    if len(history) < 10:
        return RegimeReading(Regime.UNKNOWN, 0.0, 0.0, 0.0)

    prices = [p.price for p in history]
    returns = [(prices[i] - prices[i - 1]) / prices[i - 1]
               for i in range(1, len(prices)) if prices[i - 1] != 0]
    if len(returns) < 5:
        return RegimeReading(Regime.UNKNOWN, 0.0, 0.0, 0.0)

    # Trend strength: net displacement over the window relative to the
    # sum of absolute moves — close to 1.0 means price moved steadily
    # in one direction (trending); close to 0 means lots of back-and-forth
    # with little net progress (mean-reverting/choppy).
    net_move = abs(prices[-1] - prices[0])
    total_abs_move = sum(abs(prices[i] - prices[i - 1]) for i in range(1, len(prices)))
    trend_strength = (net_move / total_abs_move) if total_abs_move > 0 else 0.0

    vol = statistics.pstdev(returns)
    reference_vol = 0.003
    volatility_level = max(0.0, min(1.0, vol / (reference_vol * 3)))

    if volatility_level > 0.7:
        regime = Regime.HIGH_VOLATILITY
    elif trend_strength > 0.5:
        regime = Regime.TRENDING
    else:
        regime = Regime.MEAN_REVERTING

    confidence = min(1.0, len(history) / lookback_periods)
    return RegimeReading(regime, round(trend_strength, 3),
                          round(volatility_level, 3), round(confidence, 3))


def is_news_risk_window(*args, **kwargs) -> bool:
    raise NotImplementedError(
        "News-risk detection requires an economic calendar data source "
        "that hasn't been chosen yet (e.g. ForexFactory, Investing.com "
        "calendar, or a paid calendar API). Do not call this until a "
        "provider is wired in — the signal engine currently does NOT "
        "check for news risk, and that gap should stay visible rather "
        "than being papered over with an always-False stub."
    )
