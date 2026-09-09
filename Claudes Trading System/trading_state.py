"""
trading_state.py

Single source of truth for "is trading currently enabled" across:
    - the risk engine (writes on hard-stop trips)
    - the kill switch (writes on manual override)
    - the dashboard (reads only; calls kill_switch() the same way a human would)
    - the notification layer (subscribes to changes, never polls)

Design goals:
    - One code path that disables + flattens, regardless of trigger source
    - Crash-safe: state survives a process restart (SQLite file, not just memory)
    - Thread-safe: risk engine and dashboard/API can run in different threads
    - Distinguishes auto-resettable disables (daily DD) from manual-reset-only
      disables (max DD, kill switch, loss streak) so a daily reset job can't
      accidentally clear something it shouldn't
    - No trading/MT5 logic in here at all — this module only tracks state and
      calls injected callbacks. Keeps it testable without a broker connection.
"""

from __future__ import annotations

import enum
import json
import sqlite3
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional


class DisableReason(str, enum.Enum):
    NONE = "none"
    MANUAL_KILL = "manual_kill"
    DAILY_DD = "daily_dd"
    MAX_DD = "max_dd"
    LOSS_STREAK = "loss_streak"
    NEWS_WINDOW = "news_window"


class DisabledBy(str, enum.Enum):
    NONE = "none"
    USER = "user"
    RISK_ENGINE = "risk_engine"
    SYSTEM = "system"  # e.g. scheduled news-window pause


# Reasons the risk engine may auto-resolve at daily rollover.
# Everything else stays disabled until a human calls reset().
AUTO_RESETTABLE = {DisableReason.DAILY_DD, DisableReason.NEWS_WINDOW}


@dataclass(frozen=True)
class TradingState:
    trading_enabled: bool
    reason: DisableReason
    disabled_by: DisabledBy
    disabled_at: Optional[str]  # ISO8601, UTC
    requires_manual_reset: bool
    note: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["reason"] = self.reason.value
        d["disabled_by"] = self.disabled_by.value
        return d


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# A listener receives (old_state, new_state) on every committed change.
StateListener = Callable[[TradingState, TradingState], None]

# Called once, synchronously, whenever a disable happens — this is where
# "close everything" logic gets hooked in from the execution layer.
# Signature: flatten(new_state: TradingState) -> None
FlattenCallback = Callable[[TradingState], None]


class TradingStateStore:
    """
    SQLite-backed state store. One row table, always id=1, so every read/write
    is a single-row upsert — simple and sufficient for a single-bot deployment.
    """

    def __init__(self, db_path: str | Path, flatten_callback: Optional[FlattenCallback] = None):
        self._db_path = str(db_path)
        self._lock = threading.RLock()
        self._listeners: list[StateListener] = []
        self._flatten_callback = flatten_callback
        self._init_db()

    # ---------- setup ----------

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trading_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    trading_enabled INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    disabled_by TEXT NOT NULL,
                    disabled_at TEXT,
                    requires_manual_reset INTEGER NOT NULL,
                    note TEXT NOT NULL DEFAULT ''
                )
                """
            )
            existing = conn.execute("SELECT id FROM trading_state WHERE id = 1").fetchone()
            if existing is None:
                # Start disabled by default — an uninitialized bot should never
                # trade by accident just because the DB file didn't exist yet.
                self._write(
                    conn,
                    TradingState(
                        trading_enabled=False,
                        reason=DisableReason.NONE,
                        disabled_by=DisabledBy.SYSTEM,
                        disabled_at=_now_iso(),
                        requires_manual_reset=True,
                        note="initial state — never enabled",
                    ),
                )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")  # safer across crashes/concurrent readers
        return conn

    # ---------- read ----------

    def get_state(self) -> TradingState:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT trading_enabled, reason, disabled_by, disabled_at, "
                "requires_manual_reset, note FROM trading_state WHERE id = 1"
            ).fetchone()
            return TradingState(
                trading_enabled=bool(row[0]),
                reason=DisableReason(row[1]),
                disabled_by=DisabledBy(row[2]),
                disabled_at=row[3],
                requires_manual_reset=bool(row[4]),
                note=row[5],
            )

    def is_enabled(self) -> bool:
        return self.get_state().trading_enabled

    # ---------- write (internal) ----------

    def _write(self, conn: sqlite3.Connection, state: TradingState) -> None:
        conn.execute(
            """
            INSERT INTO trading_state
                (id, trading_enabled, reason, disabled_by, disabled_at, requires_manual_reset, note)
            VALUES (1, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                trading_enabled=excluded.trading_enabled,
                reason=excluded.reason,
                disabled_by=excluded.disabled_by,
                disabled_at=excluded.disabled_at,
                requires_manual_reset=excluded.requires_manual_reset,
                note=excluded.note
            """,
            (
                int(state.trading_enabled),
                state.reason.value,
                state.disabled_by.value,
                state.disabled_at,
                int(state.requires_manual_reset),
                state.note,
            ),
        )

    def _commit(self, new_state: TradingState) -> TradingState:
        with self._lock:
            old_state = self.get_state()
            with self._connect() as conn:
                self._write(conn, new_state)
            for listener in self._listeners:
                # Listener errors (e.g. Telegram API down) must never break
                # the state transition itself — log and move on.
                try:
                    listener(old_state, new_state)
                except Exception as exc:  # noqa: BLE001
                    print(f"[trading_state] listener error: {exc!r}")
            if not new_state.trading_enabled and old_state.trading_enabled and self._flatten_callback:
                try:
                    self._flatten_callback(new_state)
                except Exception as exc:  # noqa: BLE001
                    # This is the one failure that matters most — surface it loudly.
                    print(f"[trading_state] FLATTEN CALLBACK FAILED: {exc!r}")
                    raise
            return new_state

    # ---------- public actions ----------

    def enable(self, note: str = "") -> TradingState:
        """Re-enable trading. Should only be reachable when no manual-reset-only
        disable is active, or after an explicit reset()."""
        with self._lock:
            current = self.get_state()
            if (
                current.reason != DisableReason.NONE
                and current.requires_manual_reset
                and current.reason not in AUTO_RESETTABLE
            ):
                raise RuntimeError(
                    f"Cannot enable: active disable '{current.reason.value}' requires reset() first."
                )
            return self._commit(
                TradingState(
                    trading_enabled=True,
                    reason=DisableReason.NONE,
                    disabled_by=DisabledBy.NONE,
                    disabled_at=None,
                    requires_manual_reset=False,
                    note=note,
                )
            )

    def disable(
        self,
        reason: DisableReason,
        by: DisabledBy,
        note: str = "",
        manual_reset_required: Optional[bool] = None,
    ) -> TradingState:
        """
        Disable trading and flatten positions via the injected callback.
        This is the ONE path both the risk engine and the kill switch use —
        see kill_switch() below, which is just a thin wrapper over this.
        """
        if manual_reset_required is None:
            manual_reset_required = reason not in AUTO_RESETTABLE
        return self._commit(
            TradingState(
                trading_enabled=False,
                reason=reason,
                disabled_by=by,
                disabled_at=_now_iso(),
                requires_manual_reset=manual_reset_required,
                note=note,
            )
        )

    def kill_switch(self, note: str = "manual kill switch") -> TradingState:
        """What the dashboard's kill button (or a CLI fallback script) calls."""
        return self.disable(
            reason=DisableReason.MANUAL_KILL,
            by=DisabledBy.USER,
            note=note,
            manual_reset_required=True,
        )

    def reset(self, note: str = "manual reset") -> TradingState:
        """Explicit human action clearing ANY disable, including manual-reset-only ones."""
        with self._lock:
            return self._commit(
                TradingState(
                    trading_enabled=True,
                    reason=DisableReason.NONE,
                    disabled_by=DisabledBy.NONE,
                    disabled_at=None,
                    requires_manual_reset=False,
                    note=note,
                )
            )

    def daily_rollover_reset(self) -> TradingState:
        """
        Called by your scheduled daily-reset job. Only clears the disable if
        the current reason is auto-resettable (e.g. daily_dd) — leaves
        max_dd / manual_kill / loss_streak disables untouched.
        """
        with self._lock:
            current = self.get_state()
            if current.trading_enabled or current.reason not in AUTO_RESETTABLE:
                return current  # nothing to do
            return self.enable(note="auto-reset at daily rollover")

    # ---------- listeners ----------

    def register_listener(self, listener: StateListener) -> None:
        """Notification layer hooks in here — one call site, fires on every change."""
        self._listeners.append(listener)


# ---------------------------------------------------------------------------
# Demo / smoke test — run directly: python trading_state.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import tempfile

    def fake_flatten(state: TradingState) -> None:
        print(f"  >> FLATTEN: closing all positions (reason={state.reason.value})")

    def notify(old: TradingState, new: TradingState) -> None:
        if old.trading_enabled != new.trading_enabled:
            status = "ENABLED" if new.trading_enabled else f"DISABLED ({new.reason.value})"
            print(f"  >> NOTIFY: trading is now {status} — by={new.disabled_by.value}")

    with tempfile.TemporaryDirectory() as tmp:
        store = TradingStateStore(Path(tmp) / "state.db", flatten_callback=fake_flatten)
        store.register_listener(notify)

        print("1. Initial state:", store.get_state().to_dict())

        print("\n2. Enabling trading for the day")
        store.enable(note="startup checks passed")
        print("   ->", store.get_state().to_dict())

        print("\n3. Risk engine trips daily DD limit")
        store.disable(DisableReason.DAILY_DD, DisabledBy.RISK_ENGINE, note="daily DD hit 2.5%")
        print("   ->", store.get_state().to_dict())

        print("\n4. Daily rollover job runs — should auto-clear daily_dd")
        store.daily_rollover_reset()
        print("   ->", store.get_state().to_dict())

        print("\n5. Risk engine trips MAX DD (manual-reset-only)")
        store.disable(DisableReason.MAX_DD, DisabledBy.RISK_ENGINE, note="max DD hit 6%")
        print("   ->", store.get_state().to_dict())

        print("\n6. Daily rollover job runs — should NOT clear max_dd")
        store.daily_rollover_reset()
        print("   ->", store.get_state().to_dict())

        print("\n7. Attempting enable() directly — should raise")
        try:
            store.enable()
        except RuntimeError as e:
            print("   -> correctly blocked:", e)

        print("\n8. Human calls reset() explicitly")
        store.reset(note="reviewed the day, restarting")
        print("   ->", store.get_state().to_dict())

        print("\n9. User hits the kill switch from the dashboard")
        store.kill_switch(note="pressed from dashboard UI")
        print("   ->", store.get_state().to_dict())