package messaging

import "time"

// SignalMessage: Rust (Brain) ➔ Go (Shield)
type SignalMessage struct {
	MsgType          string             `json:"msg_type"` // "SIGNAL"
	TimestampUTC     time.Time          `json:"timestamp_utc"`
	Symbol           string             `json:"symbol"`
	Direction        string             `json:"direction"` // "LONG" or "SHORT"
	ConfidencePct    float64            `json:"confidence_pct"`
	Regime           string             `json:"regime"`
	Components       map[string]float64 `json:"components"` // w1, w2, w3, w4, w5
	ExcludedTerms    []string           `json:"excluded_terms"`
	ProposedRRRatio  float64            `json:"proposed_rr_ratio"`
	ProposedStop     float64            `json:"proposed_stop_price"`
	ProposedTP       float64            `json:"proposed_tp_price"`
	SignalID         string             `json:"signal_id"`
}

// DecisionMessage: Go (Shield) ➔ Python (Hands)
type DecisionMessage struct {
	MsgType               string   `json:"msg_type"` // "DECISION"
	TimestampUTC          time.Time `json:"timestamp_utc"`
	SignalID              string   `json:"signal_id"`
	Symbol                string   `json:"symbol"`
	Approved              bool     `json:"approved"`
	RejectionReasons      []string `json:"rejection_reasons"`
	ApprovedRiskPct       float64  `json:"approved_risk_pct"` // e.g., 0.0075 for 0.75%
	CorrelationGroup      string   `json:"correlation_group"`
	CurrentUSDExposure    int      `json:"current_usd_exposure"`
}

// StateMessage: Go (Shield) ➔ Python (Dashboard)
type StateMessage struct {
	MsgType           string  `json:"msg_type"` // "STATE"
	TimestampUTC      time.Time `json:"timestamp_utc"`
	TradingEnabled    bool    `json:"trading_enabled"`
	CurrentEquity     float64 `json:"current_equity"`
	DailyDDPct        float64 `json:"daily_dd_pct"`
	MaxDDPct          float64 `json:"max_dd_pct"`
	ConsecutiveLosses int     `json:"consecutive_losses"`
	KillSwitchActive  bool    `json:"kill_switch_active"`
}