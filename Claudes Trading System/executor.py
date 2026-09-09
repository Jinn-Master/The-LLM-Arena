"""
mt5_bridge/executor.py

Thin execution bridge to MetaTrader 5 using the official `MetaTrader5`
Python package (MetaQuotes-maintained). This module is deliberately
"dumb" — it does not decide whether a trade should happen. Every
method that would place, modify, or close a trade requires a
pre-approved GovernorDecision from risk_engine.governor.RiskGovernor.
This bridge will refuse to act without one, on principle: the risk
governor is the single place decisions get made, and this file must
never grow its own opinion about whether a trade is a good idea.

NOT LIVE-TESTED IN THIS SESSION:
- The `MetaTrader5` package only works on Windows, requires an MT5
  terminal installed and logged in, and this sandbox has neither
  Windows nor network access. Before trusting this against Alpha
  Capital's real evaluation account:
    1. pip install MetaTrader5
    2. Run against a DEMO account first, not the evaluation account.
    3. Confirm order fill behavior, symbol naming (brokers vary —
       e.g. "EURUSD" vs "EURUSD.a" vs "EURUSDm"), and lot-size
       rounding against your specific Alpha Capital broker feed.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from risk_engine.governor import GovernorDecision, TradeRequest

logger = logging.getLogger("mt5_bridge.executor")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


@dataclass
class OrderResult:
    success: bool
    ticket: Optional[int]
    message: str
    raw_retcode: Optional[int] = None


@dataclass
class PositionInfo:
    ticket: int
    symbol: str
    direction: str          # "LONG" or "SHORT"
    volume: float
    open_price: float
    current_price: float
    profit: float
    opened_at: datetime


class RiskViolation(Exception):
    """Raised whenever anything tries to execute without governor approval.
    This should never happen in correct calling code — it exists as a
    hard backstop, not an expected control-flow path."""
    pass


class MT5ExecutionBridge:
    def __init__(self):
        try:
            import MetaTrader5 as mt5
        except ImportError as e:
            raise ImportError(
                "MetaTrader5 package not installed or not on Windows. "
                "Run: pip install MetaTrader5 (Windows only, requires the "
                "MT5 terminal to be installed and logged in)."
            ) from e
        self._mt5 = mt5
        self._connected = False

    def connect(self, login: Optional[int] = None, password: Optional[str] = None,
                server: Optional[str] = None) -> bool:
        """If the MT5 terminal is already running and logged in, calling
        initialize() with no arguments attaches to that session — the
        preferred path, so credentials don't need to live in this code
        at all. Only pass login/password/server for a headless setup,
        and pull those from environment variables or a secrets manager,
        never hardcode them."""
        if login and password and server:
            ok = self._mt5.initialize(login=login, password=password, server=server)
        else:
            ok = self._mt5.initialize()
        self._connected = ok
        if not ok:
            logger.error("MT5 connect failed: %s", self._mt5.last_error())
        else:
            logger.info("Connected to MT5 terminal.")
        return ok

    def disconnect(self) -> None:
        self._mt5.shutdown()
        self._connected = False

    def _require_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("Not connected to MT5. Call connect() first.")

    # ------------------------------------------------------------------
    # Read-only operations — no governor check needed, these don't act.
    # ------------------------------------------------------------------
    def get_account_equity(self) -> float:
        self._require_connected()
        info = self._mt5.account_info()
        if info is None:
            raise RuntimeError(f"Failed to get account info: {self._mt5.last_error()}")
        return float(info.equity)

    def get_account_balance(self) -> float:
        self._require_connected()
        info = self._mt5.account_info()
        if info is None:
            raise RuntimeError(f"Failed to get account info: {self._mt5.last_error()}")
        return float(info.balance)

    def get_open_positions(self) -> List[PositionInfo]:
        self._require_connected()
        positions = self._mt5.positions_get()
        if positions is None:
            return []
        results = []
        for p in positions:
            results.append(PositionInfo(
                ticket=p.ticket,
                symbol=p.symbol,
                direction="LONG" if p.type == self._mt5.ORDER_TYPE_BUY else "SHORT",
                volume=p.volume,
                open_price=p.price_open,
                current_price=p.price_current,
                profit=p.profit,
                opened_at=datetime.fromtimestamp(p.time, tz=timezone.utc),
            ))
        return results

    # ------------------------------------------------------------------
    # State-changing operations — ALL require a pre-approved decision.
    # ------------------------------------------------------------------
    def execute_trade(self, trade: TradeRequest, decision: GovernorDecision,
                       symbol_mt5_name: str, volume_lots: float,
                       stop_loss_price: float, take_profit_price: float) -> OrderResult:
        self._require_connected()
        self._assert_approved(decision)

        order_type = (self._mt5.ORDER_TYPE_BUY if trade.direction == "LONG"
                      else self._mt5.ORDER_TYPE_SELL)
        tick = self._mt5.symbol_info_tick(symbol_mt5_name)
        if tick is None:
            return OrderResult(success=False, ticket=None,
                                message=f"No tick data for {symbol_mt5_name}")
        price = tick.ask if trade.direction == "LONG" else tick.bid

        request = {
            "action": self._mt5.TRADE_ACTION_DEAL,
            "symbol": symbol_mt5_name,
            "volume": volume_lots,
            "type": order_type,
            "price": price,
            "sl": stop_loss_price,
            "tp": take_profit_price,
            "deviation": 10,
            "magic": 20260908,  # identifies orders placed by this system
            "comment": f"governed:{trade.source}",
            "type_time": self._mt5.ORDER_TIME_GTC,
            "type_filling": self._mt5.ORDER_FILLING_IOC,
        }

        result = self._mt5.order_send(request)
        if result is None:
            msg = f"order_send returned None: {self._mt5.last_error()}"
            logger.error(msg)
            return OrderResult(success=False, ticket=None, message=msg)

        success = result.retcode == self._mt5.TRADE_RETCODE_DONE
        if not success:
            logger.error("Order failed [%s %s]: retcode=%s comment=%s",
                         trade.direction, symbol_mt5_name, result.retcode, result.comment)
        else:
            logger.info("Order filled [%s %s] ticket=%s",
                       trade.direction, symbol_mt5_name, result.order)

        return OrderResult(
            success=success,
            ticket=result.order if success else None,
            message=result.comment,
            raw_retcode=result.retcode,
        )

    def close_all_positions(self, decision: GovernorDecision, reason: str) -> List[OrderResult]:
        """Used by the manual override / kill switch. Requires an
        approved decision same as any other state change — even
        closing positions goes through the governor's audit trail,
        so 'why did we close everything' is always answerable."""
        self._require_connected()
        self._assert_approved(decision, allow_override_close=True)

        results = []
        for pos in self.get_open_positions():
            tick = self._mt5.symbol_info_tick(pos.symbol)
            close_type = (self._mt5.ORDER_TYPE_SELL if pos.direction == "LONG"
                          else self._mt5.ORDER_TYPE_BUY)
            price = tick.bid if pos.direction == "LONG" else tick.ask
            request = {
                "action": self._mt5.TRADE_ACTION_DEAL,
                "symbol": pos.symbol,
                "volume": pos.volume,
                "type": close_type,
                "position": pos.ticket,
                "price": price,
                "deviation": 20,
                "magic": 20260908,
                "comment": f"closed:{reason}",
                "type_time": self._mt5.ORDER_TIME_GTC,
                "type_filling": self._mt5.ORDER_FILLING_IOC,
            }
            result = self._mt5.order_send(request)
            success = result is not None and result.retcode == self._mt5.TRADE_RETCODE_DONE
            results.append(OrderResult(
                success=success,
                ticket=pos.ticket if success else None,
                message=result.comment if result else "order_send returned None",
                raw_retcode=result.retcode if result else None,
            ))
        logger.warning("close_all_positions executed (%s): %d positions closed, %d failed",
                       reason, sum(r.success for r in results),
                       sum(not r.success for r in results))
        return results

    def _assert_approved(self, decision: GovernorDecision,
                          allow_override_close: bool = False) -> None:
        """Hard backstop: refuses to act on anything but an approved
        decision. allow_override_close exists ONLY for close_all_positions
        during a manual-override event, where the decision itself may
        reflect a breach (that's WHY we're closing) but the close action
        is the correct response to it, not a bypass of it."""
        if decision.approved:
            return
        if allow_override_close:
            return
        raise RiskViolation(
            f"Refusing to execute: governor decision was not approved. "
            f"Reasons: {decision.reasons}"
        )
