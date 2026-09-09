package risk

import (
	"log"
	"qwen-trading/messaging"
	"time"
)

type PropFirmConfig struct {
	InitialBalance          float64
	MaxDailyDDPct           float64 // 0.015 (1.5% for Stellar 3% limit)
	MaxTotalDDPct           float64 // 0.040 (4.0% for Stellar 8% limit)
	MaxConsecutiveLosses    int     // 3
	MaxCorrelatedUSDTrades  int     // 2
	MinRiskPct              float64 // 0.005 (0.50%)
	MaxRiskPct              float64 // 0.0075 (0.75%)
}

var USD_CORRELATED_ASSETS = map[string]bool{
	"EURUSD": true, "GBPUSD": true, "AUDUSD": true, "USDCAD": true,
	"XAUUSD": true, "NAS100": true, "US500": true,
}

type RiskEngine struct {
	config             PropFirmConfig
	state              *TradingStateStore
	broker             *messaging.MessageBroker
	consecutiveLosses  int
	dailyStartEquity   float64
	lastResetDate      time.Time
}

func NewRiskEngine(config PropFirmConfig, state *TradingStateStore, broker *messaging.MessageBroker) *RiskEngine {
	return &RiskEngine{
		config:           config,
		state:            state,
		broker:           broker,
		dailyStartEquity: config.InitialBalance,
		lastResetDate:    time.Now(),
	}
}

func (re *RiskEngine) EvaluateSignal(sig messaging.SignalMessage) messaging.DecisionMessage {
	decision := messaging.DecisionMessage{
		MsgType:          "DECISION",
		TimestampUTC:     time.Now().UTC(),
		SignalID:         sig.SignalID,
		Symbol:           sig.Symbol,
		Approved:         false,
		RejectionReasons: []string{},
	}

	// 1. Check Kill Switch / Manual Disable
	if !re.state.IsTradingEnabled() {
		decision.RejectionReasons = append(decision.RejectionReasons, "TRADING_DISABLED_BY_STATE")
		return decision
	}

	// 2. Check Daily DD (1.5%)
	currentEquity := re.state.GetCurrentEquity() // Fetched from MT5 via Python feedback
	dailyLossPct := (re.dailyStartEquity - currentEquity) / re.dailyStartEquity
	if dailyLossPct >= re.config.MaxDailyDDPct {
		decision.RejectionReasons = append(decision.RejectionReasons, "DAILY_DD_LIMIT_1.5%_BREACHED")
		re.state.Disable("DAILY_DD", "risk_engine")
		return decision
	}

	// 3. Check Max DD (4.0%)
	totalLossPct := (re.config.InitialBalance - currentEquity) / re.config.InitialBalance
	if totalLossPct >= re.config.MaxTotalDDPct {
		decision.RejectionReasons = append(decision.RejectionReasons, "MAX_DD_LIMIT_4.0%_BREACHED")
		re.state.Disable("MAX_DD", "risk_engine")
		return decision
	}

	// 4. Check Consecutive Losses
	if re.consecutiveLosses >= re.config.MaxConsecutiveLosses {
		decision.RejectionReasons = append(decision.RejectionReasons, "MAX_CONSECUTIVE_LOSSES_3_REACHED")
		re.state.Disable("LOSS_STREAK", "risk_engine")
		return decision
	}

	// 5. Check Correlation Exposure (Max 2 USD Trades)
	usdExposureCount := re.state.GetOpenCorrelatedUSDCount()
	if USD_CORRELATED_ASSETS[sig.Symbol] && usdExposureCount >= re.config.MaxCorrelatedUSDTrades {
		decision.RejectionReasons = append(decision.RejectionReasons, "MAX_CORRELATED_USD_EXPOSURE_2_REACHED")
		return decision
	}

	// 6. Check R:R Ratio (Min 1:2)
	if sig.ProposedRRRatio < 2.0 {
		decision.RejectionReasons = append(decision.RejectionReasons, "RR_RATIO_BELOW_1:2_MINIMUM")
		return decision
	}

	// ALL CHECKS PASSED
	decision.Approved = true
	decision.ApprovedRiskPct = re.config.MaxRiskPct // Could be dynamic based on confidence
	decision.CurrentUSDExposure = usdExposureCount
	if USD_CORRELATED_ASSETS[sig.Symbol] {
		decision.CorrelationGroup = "USD_CORRELATED"
	}

	return decision
}

func (re *RiskEngine) RecordTradeResult(isProfitable bool) {
	if !isProfitable {
		re.consecutiveLosses++
		if re.consecutiveLosses >= re.config.MaxConsecutiveLosses {
			re.state.Disable("LOSS_STREAK", "risk_engine")
		}
	} else {
		re.consecutiveLosses = 0
	}
}