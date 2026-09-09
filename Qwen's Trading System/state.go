package risk

import (
	"database/sql"
	"log"
	"time"
	_ "github.com/mattn/go-sqlite3"
)

type TradingStateStore struct {
	db *sql.DB
}

func NewStateStore(dbPath string) *TradingStateStore {
	db, err := sql.Open("sqlite3", dbPath)
	if err != nil {
		log.Fatal(err)
	}
	
	// Create table
	db.Exec(`CREATE TABLE IF NOT EXISTS system_state (
		id INTEGER PRIMARY KEY CHECK (id = 1),
		trading_enabled INTEGER NOT NULL DEFAULT 0,
		disable_reason TEXT DEFAULT 'NONE',
		current_equity REAL DEFAULT 100000.0,
		open_usd_correlated_count INTEGER DEFAULT 0
	)`)
	
	// Initialize if empty
	db.Exec(`INSERT OR IGNORE INTO system_state (id, trading_enabled, disable_reason) VALUES (1, 0, 'INITIAL_UNSAFE_STATE')`)
	
	return &TradingStateStore{db: db}
}

func (s *TradingStateStore) IsTradingEnabled() bool {
	var enabled int
	s.db.QueryRow("SELECT trading_enabled FROM system_state WHERE id = 1").Scan(&enabled)
	return enabled == 1
}

func (s *TradingStateStore) Disable(reason string, source string) {
	log.Printf("[STATE] 🚨 DISABLED: Reason=%s, Source=%s", reason, source)
	s.db.Exec("UPDATE system_state SET trading_enabled = 0, disable_reason = ? WHERE id = 1", reason)
	// In production: Trigger Flatten Callback to close all MT5 positions
}

func (s *TradingStateStore) Enable() {
	log.Println("[STATE] ✅ Trading ENABLED")
	s.db.Exec("UPDATE system_state SET trading_enabled = 1, disable_reason = 'NONE' WHERE id = 1")
}

func (s *TradingStateStore) GetCurrentEquity() float64 {
	var equity float64
	s.db.QueryRow("SELECT current_equity FROM system_state WHERE id = 1").Scan(&equity)
	return equity
}

func (s *TradingStateStore) UpdateEquity(equity float64) {
	s.db.Exec("UPDATE system_state SET current_equity = ? WHERE id = 1", equity)
}

func (s *TradingStateStore) GetOpenCorrelatedUSDCount() int {
	var count int
	s.db.QueryRow("SELECT open_usd_correlated_count FROM system_state WHERE id = 1").Scan(&count)
	return count
}

func (s *TradingStateStore) UpdateCorrelatedCount(count int) {
	s.db.Exec("UPDATE system_state SET open_usd_correlated_count = ? WHERE id = 1", count)
}