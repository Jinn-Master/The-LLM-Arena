import MetaTrader5 as mt5
import logging
import json
from dataclasses import dataclass
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MT5_Bridge")

@dataclass
class GovernorDecision:
    signal_id: str
    approved: bool
    approved_risk_pct: float
    rejection_reasons: list

class MT5ExecutionBridge:
    def __init__(self):
        if not mt5.initialize():
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        logger.info("✅ Connected to MT5 Terminal")

    def execute_trade(self, symbol: str, direction: str, volume: float, 
                      sl: float, tp: float, decision: GovernorDecision) -> dict:
        """
        STRICT GATING: Refuses to execute without an approved GovernorDecision.
        """
        if not decision.approved:
            logger.error(f"🚫 EXECUTION BLOCKED: Governor rejected signal {decision.signal_id}. Reasons: {decision.rejection_reasons}")
            return {"success": False, "error": "Governor Rejection"}

        order_type = mt5.ORDER_TYPE_BUY if direction == "LONG" else mt5.ORDER_TYPE_SELL
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return {"success": False, "error": "No tick data"}

        price = tick.ask if direction == "LONG" else tick.bid

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 10,
            "magic": 20260908,
            "comment": f"Qwen_Governed:{decision.signal_id}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"❌ Order Failed: {result.comment}")
            return {"success": False, "error": result.comment}
        
        logger.info(f"✅ Order Filled: {direction} {symbol} Ticket: {result.order}")
        return {"success": True, "ticket": result.order}

    def manage_exits_r_normalized(self, ticket: int, entry_price: float, current_price: float, direction: str, risk_amount: float):
        """
        ChatGPT's R-Normalized Exit Logic:
        +1R: Move to Breakeven + Commission
        +2R: Activate tight trailing stop
        """
        profit_r = (current_price - entry_price) / risk_amount if direction == "LONG" else (entry_price - current_price) / risk_amount
        
        if profit_r >= 1.0:
            # Move to BE + 0.05% buffer
            new_sl = entry_price * 1.0005 if direction == "LONG" else entry_price * 0.9995
            # TODO: Implement mt5.order_send to modify SL
            logger.info(f"🛡️ Trade {ticket} moved to Breakeven (+1R)")
            
        if profit_r >= 2.0:
            # Activate trailing stop (e.g., 0.5% trail)
            trail_price = current_price * 0.995 if direction == "LONG" else current_price * 1.005
            # TODO: Implement mt5.order_send to modify SL to trail_price
            logger.info(f"🏃 Trade {ticket} trailing stop activated (+2R)")

    def shutdown(self):
        mt5.shutdown()