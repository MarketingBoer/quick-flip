import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

DB_PATH = os.path.expanduser("~/Projects/quick-flip/user_data/learning.db")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ft_trade_id TEXT,
            pair TEXT NOT NULL,
            setup_type TEXT NOT NULL,
            entry_thesis TEXT,
            market_regime TEXT,
            confluence_score REAL,
            ai_confidence REAL,
            conviction_level TEXT,
            what_could_go_wrong TEXT,
            edge_description TEXT,
            source TEXT DEFAULT 'live',
            thesis_quality TEXT,
            validation_status TEXT,
            evaluation_notes TEXT,
            profit_pct REAL,
            exit_reason TEXT,
            duration_minutes REAL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_predictions_pair_setup_created
            ON predictions(pair, setup_type, created_at);

        CREATE TABLE IF NOT EXISTS patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            setup_type TEXT NOT NULL,
            pair TEXT NOT NULL,
            market_regime TEXT NOT NULL,
            total_trades INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            win_rate REAL DEFAULT 0.0,
            avg_profit_pct REAL DEFAULT 0.0,
            rating TEXT DEFAULT 'NEUTRAL',
            last_updated TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(setup_type, pair, market_regime)
        );

        CREATE TABLE IF NOT EXISTS regime_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            btc_price REAL,
            btc_ema_20 REAL,
            btc_ema_50 REAL,
            atr_ratio REAL,
            regime TEXT,
            confidence REAL,
            timestamp TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            query TEXT,
            answer TEXT,
            source TEXT,
            valid_until TEXT,
            still_valid INTEGER DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_knowledge_still_valid
            ON knowledge(still_valid);

        CREATE TABLE IF NOT EXISTS call_counter (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE,
            count INTEGER DEFAULT 0
        );
    """)
    conn.close()


def save_prediction(
    pair: str,
    setup_type: str,
    entry_thesis: str = "",
    market_regime: str = "",
    confluence_score: float = 0.0,
    ai_confidence: float = 0.0,
    conviction_level: str = "",
    what_could_go_wrong: str = "",
    edge_description: str = "",
    source: str = "live",
    ft_trade_id: Optional[str] = None,
) -> int:
    conn = _get_conn()
    cur = conn.execute(
        """INSERT INTO predictions
           (ft_trade_id, pair, setup_type, entry_thesis, market_regime,
            confluence_score, ai_confidence, conviction_level,
            what_could_go_wrong, edge_description, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (ft_trade_id, pair, setup_type, entry_thesis, market_regime,
         confluence_score, ai_confidence, conviction_level,
         what_could_go_wrong, edge_description, source),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id


def update_evaluation(
    prediction_id: int,
    thesis_quality: str,
    validation_status: str,
    evaluation_notes: str,
    profit_pct: float,
    exit_reason: str,
    duration_minutes: float,
    ft_trade_id: Optional[str] = None,
):
    conn = _get_conn()
    params = [thesis_quality, validation_status, evaluation_notes,
              profit_pct, exit_reason, duration_minutes]
    sql = """UPDATE predictions SET
             thesis_quality=?, validation_status=?, evaluation_notes=?,
             profit_pct=?, exit_reason=?, duration_minutes=?"""
    if ft_trade_id is not None:
        sql += ", ft_trade_id=?"
        params.append(ft_trade_id)
    sql += " WHERE id=?"
    params.append(prediction_id)
    conn.execute(sql, params)
    conn.commit()
    conn.close()


def get_pattern_rating(setup_type: str, pair: str, market_regime: str) -> str:
    conn = _get_conn()
    row = conn.execute(
        "SELECT rating FROM patterns WHERE setup_type=? AND pair=? AND market_regime=?",
        (setup_type, pair, market_regime),
    ).fetchone()
    conn.close()
    if row:
        return row["rating"]
    return "NEUTRAL"


def get_pair_history(pair: str, setup_type: str, limit: int = 5) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        """SELECT * FROM predictions
           WHERE pair=? AND setup_type=?
           ORDER BY created_at DESC LIMIT ?""",
        (pair, setup_type, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def increment_daily_calls() -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    conn = _get_conn()
    conn.execute(
        """INSERT INTO call_counter (date, count) VALUES (?, 1)
           ON CONFLICT(date) DO UPDATE SET count = count + 1""",
        (today,),
    )
    conn.commit()
    row = conn.execute(
        "SELECT count FROM call_counter WHERE date=?", (today,)
    ).fetchone()
    conn.close()
    return row["count"]


def get_daily_calls() -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    conn = _get_conn()
    row = conn.execute(
        "SELECT count FROM call_counter WHERE date=?", (today,)
    ).fetchone()
    conn.close()
    return row["count"] if row else 0


def get_relevant_knowledge(
    pair: Optional[str] = None,
    setup_type: Optional[str] = None,
    limit: int = 5,
) -> list[dict]:
    conn = _get_conn()
    conditions = ["still_valid = 1"]
    params: list = []

    if pair:
        conditions.append("answer LIKE ?")
        params.append(f"%{pair}%")
    if setup_type:
        conditions.append("answer LIKE ?")
        params.append(f"%{setup_type}%")

    where = " AND ".join(conditions)
    rows = conn.execute(
        f"SELECT * FROM knowledge WHERE {where} ORDER BY created_at DESC LIMIT ?",
        params + [limit],
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_knowledge(
    category: str,
    query: str,
    answer: str,
    source: str = "research",
    valid_until: Optional[str] = None,
):
    conn = _get_conn()
    conn.execute(
        """INSERT INTO knowledge (category, query, answer, source, valid_until)
           VALUES (?, ?, ?, ?, ?)""",
        (category, query, answer, source, valid_until),
    )
    conn.commit()
    conn.close()


def save_regime_snapshot(
    btc_price: float,
    btc_ema_20: float,
    btc_ema_50: float,
    atr_ratio: float,
    regime: str,
    confidence: float,
):
    conn = _get_conn()
    conn.execute(
        """INSERT INTO regime_snapshots
           (btc_price, btc_ema_20, btc_ema_50, atr_ratio, regime, confidence)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (btc_price, btc_ema_20, btc_ema_50, atr_ratio, regime, confidence),
    )
    conn.commit()
    conn.close()


def expire_knowledge():
    now = datetime.now().isoformat()
    conn = _get_conn()
    conn.execute(
        "UPDATE knowledge SET still_valid=0 WHERE valid_until IS NOT NULL AND valid_until < ?",
        (now,),
    )
    conn.commit()
    conn.close()


def get_predictions_for_aggregation() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        """SELECT pair, setup_type, market_regime, profit_pct
           FROM predictions
           WHERE profit_pct IS NOT NULL AND source IN ('backtest', 'live')"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def upsert_pattern(
    setup_type: str,
    pair: str,
    market_regime: str,
    total_trades: int,
    wins: int,
    losses: int,
    win_rate: float,
    avg_profit_pct: float,
    rating: str,
):
    conn = _get_conn()
    conn.execute(
        """INSERT INTO patterns
           (setup_type, pair, market_regime, total_trades, wins, losses,
            win_rate, avg_profit_pct, rating, last_updated)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(setup_type, pair, market_regime)
           DO UPDATE SET
             total_trades=excluded.total_trades,
             wins=excluded.wins,
             losses=excluded.losses,
             win_rate=excluded.win_rate,
             avg_profit_pct=excluded.avg_profit_pct,
             rating=excluded.rating,
             last_updated=datetime('now')""",
        (setup_type, pair, market_regime, total_trades, wins, losses,
         win_rate, avg_profit_pct, rating),
    )
    conn.commit()
    conn.close()


def get_prediction_by_pair_time(pair: str, created_after: str) -> Optional[dict]:
    conn = _get_conn()
    row = conn.execute(
        """SELECT * FROM predictions
           WHERE pair=? AND created_at >= ? AND source='live'
           ORDER BY created_at DESC LIMIT 1""",
        (pair, created_after),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_prediction_trade_id(prediction_id: int, ft_trade_id: str):
    conn = _get_conn()
    conn.execute(
        "UPDATE predictions SET ft_trade_id=? WHERE id=?",
        (ft_trade_id, prediction_id),
    )
    conn.commit()
    conn.close()


def get_prediction_by_trade_id(ft_trade_id: str) -> Optional[dict]:
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM predictions WHERE ft_trade_id=? ORDER BY created_at DESC LIMIT 1",
        (ft_trade_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
