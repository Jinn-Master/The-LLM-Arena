"""
signal_engine/engine.py

Combines the individual components into the final signal, matching
the spec's example output shape:
    Signal: LONG (USDCAD), Confidence: 82%

Design commitments carried over from the rest of the system:
- Every excluded term (missing data) is recorded in the result, not
  hidden — you should always be able to see WHY a given signal only
  used 2 of 5 terms.
- Confidence is explicitly reduced when fewer terms were available,
  not computed as if a partial signal were as trustworthy as a full one.
- This module makes no claim about whether a signal should be acted
  on — that's the risk governor's job downstream. This only answers
  "what does the data suggest," honestly, including its own gaps.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional

from data_layer.providers.base import DataProvider
from signal_engine import components
from signal_engine.regime import detect_regime, Regime, RegimeReading
from signal_engine.weights import SignalWeights, DEFAULT_WEIGHTS, renormalize_excluding


@dataclass
class Signal:
    symbol: str
    direction: str              # "LONG", "SHORT", or "NEUTRAL"
    raw_score: float            # signed, roughly [-1, 1] before confidence scaling
    confidence_pct: float        # 0-100
    regime: RegimeReading
    terms_used: Dict[str, float] = field(default_factory=dict)
    terms_excluded: list = field(default_factory=list)
    weights_used: Dict[str, float] = field(default_factory=dict)

    def summary(self) -> str:
        excluded_note = (f" [excluded: {', '.join(self.terms_excluded)}]"
                          if self.terms_excluded else "")
        return (f"{self.direction} ({self.symbol}), "
                f"Confidence: {self.confidence_pct:.0f}%, "
                f"Regime: {self.regime.regime.value}{excluded_note}")


class SignalEngine:
    def __init__(self, provider: DataProvider, weights: SignalWeights = None):
        self.provider = provider
        self.weights = weights or DEFAULT_WEIGHTS

    def generate(self, symbol: str) -> Signal:
        raw_terms = {
            "w1_futures_momentum": components.futures_momentum(self.provider, symbol),
            "w2_order_flow": components.order_flow(self.provider, symbol),
            "w3_lead_lag": components.lead_lag(self.provider, symbol),
            "w4_macro_confirmation": components.macro_confirmation(self.provider, symbol),
        }
        vol_risk = components.volatility_risk(self.provider, symbol)

        excluded = [k for k, v in raw_terms.items() if v is None]
        included_terms = {k: v for k, v in raw_terms.items() if v is not None}

        regime = detect_regime(self.provider, symbol)

        if not included_terms:
            # Every directional term unavailable — cannot honestly produce
            # a signal. Return NEUTRAL with 0 confidence rather than guess.
            return Signal(symbol=symbol, direction="NEUTRAL", raw_score=0.0,
                          confidence_pct=0.0, regime=regime,
                          terms_used={}, terms_excluded=excluded,
                          weights_used={})

        active_weights = renormalize_excluding(self.weights, excluded)

        weighted_sum = sum(active_weights[k] * v for k, v in included_terms.items())

        vol_penalty = 0.0
        if vol_risk is not None:
            vol_penalty = self.weights.w5_volatility_risk * vol_risk
        else:
            excluded.append("w5_volatility_risk")

        raw_score = weighted_sum - vol_penalty
        raw_score = max(-1.0, min(1.0, raw_score))

        if raw_score > 0.05:
            direction = "LONG"
        elif raw_score < -0.05:
            direction = "SHORT"
        else:
            direction = "NEUTRAL"

        # Confidence combines: signal magnitude, how many terms were
        # available, and the regime detector's own confidence in its read.
        data_completeness = len(included_terms) / 4  # 4 directional terms total
        magnitude_confidence = abs(raw_score)
        confidence = (0.5 * data_completeness + 0.3 * magnitude_confidence
                      + 0.2 * regime.confidence)
        confidence_pct = round(max(0.0, min(1.0, confidence)) * 100, 1)

        return Signal(
            symbol=symbol,
            direction=direction,
            raw_score=round(raw_score, 4),
            confidence_pct=confidence_pct,
            regime=regime,
            terms_used=included_terms,
            terms_excluded=excluded,
            weights_used=active_weights,
        )
