"""
signal_engine/weights.py

Weights for: Signal = w1*FuturesMomentum + w2*OrderFlow + w3*LeadLag
                       + w4*MacroConfirmation - w5*VolatilityRisk

Per the decision to build with hand-tuned starting weights first and
validate with walk-forward optimization before risking real money —
these are a reasonable starting point based on domain logic, NOT
fitted to any data. Treat every number here as provisional until the
NautilusTrader walk-forward harness has actually tested it.

Reasoning behind the starting values:
- FuturesMomentum and MacroConfirmation get the highest weight — they're
  the most directly interpretable inputs given the data we actually have.
- OrderFlow and LeadLag are weighted lower NOT because they're less
  important in theory, but because we currently have no honest order-flow
  data source, and only a partial futures counterpart for lead-lag
  (Gold only). Keeping their default weight modest limits how much a
  term we can't reliably compute right now can distort the signal
  once it IS available.
- VolatilityRisk is a penalty (subtracted), sized to meaningfully
  reduce confidence in high-vol conditions without alone being able
  to flip a signal's direction.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SignalWeights:
    w1_futures_momentum: float = 0.30
    w2_order_flow: float = 0.15
    w3_lead_lag: float = 0.15
    w4_macro_confirmation: float = 0.30
    w5_volatility_risk: float = 0.10  # subtracted, not added

    def as_dict(self) -> dict:
        return {
            "w1_futures_momentum": self.w1_futures_momentum,
            "w2_order_flow": self.w2_order_flow,
            "w3_lead_lag": self.w3_lead_lag,
            "w4_macro_confirmation": self.w4_macro_confirmation,
            "w5_volatility_risk": self.w5_volatility_risk,
        }


DEFAULT_WEIGHTS = SignalWeights()


def renormalize_excluding(weights: SignalWeights, excluded_keys: list) -> dict:
    """When a term's data isn't available (e.g. no order-flow source),
    we don't silently zero it out and leave the rest as-is — that would
    quietly shrink the signal's magnitude and make confidence numbers
    mean something different depending on which data happened to be
    available that day. Instead, redistribute the excluded weight
    proportionally across the remaining terms, so the weights actually
    used always sum to the same total as the full set. Every exclusion
    is logged by the caller (signal_engine/engine.py) so it's visible,
    not silent.
    """
    all_weights = weights.as_dict()
    included = {k: v for k, v in all_weights.items() if k not in excluded_keys}
    included_total = sum(included.values())
    original_total = sum(all_weights.values())
    if included_total == 0:
        raise ValueError("All signal terms excluded — cannot compute a signal.")
    scale = original_total / included_total
    return {k: v * scale for k, v in included.items()}
