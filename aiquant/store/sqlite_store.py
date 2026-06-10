"""SQLite 存储层：用户配置、回测记录、交易日志。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from aiquant.config.logger import logger
from aiquant.config.settings import settings


class SQLiteStore:
    """SQLite 配置/日志存储。"""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path or settings.sqlite_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS backtest_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                config_json TEXT NOT NULL,
                total_return REAL,
                annual_return REAL,
                max_drawdown REAL,
                sharpe_ratio REAL,
                win_rate REAL,
                total_trades INTEGER,
                final_value REAL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS trade_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL,
                shares INTEGER,
                amount REAL,
                commission REAL,
                FOREIGN KEY (run_id) REFERENCES backtest_runs(id)
            );

            CREATE TABLE IF NOT EXISTS chat_sessions (
                session_id TEXT PRIMARY KEY,
                messages_json TEXT NOT NULL,
                current_strategy_json TEXT,
                status TEXT DEFAULT 'active',
                loop_count INTEGER DEFAULT 0,
                error_signature TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT,
                FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id)
            );

            CREATE TABLE IF NOT EXISTS llm_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                provider TEXT NOT NULL DEFAULT 'deepseek',
                api_key TEXT NOT NULL,
                base_url TEXT,
                model TEXT NOT NULL DEFAULT 'deepseek-chat',
                max_tokens INTEGER NOT NULL DEFAULT 4096,
                temperature REAL NOT NULL DEFAULT 0.1,
                updated_at TEXT NOT NULL
            );
        """)

    def save_backtest_run(self, name: str, config_json: str, report: dict) -> int:
        """保存一次回测记录，返回 run_id。"""
        cursor = self.conn.execute(
            """INSERT INTO backtest_runs
               (name, config_json, total_return, annual_return, max_drawdown,
                sharpe_ratio, win_rate, total_trades, final_value, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                name, config_json,
                report.get("total_return"), report.get("annual_return"),
                report.get("max_drawdown"), report.get("sharpe_ratio"),
                report.get("win_rate"), report.get("total_trades"),
                report.get("final_value"),
                datetime.now().isoformat(),
            ],
        )
        self.conn.commit()
        return cursor.lastrowid

    def save_trades(self, run_id: int, trades: list[dict]):
        """保存交易记录。"""
        for t in trades:
            self.conn.execute(
                """INSERT INTO trade_logs
                   (run_id, ticker, trade_date, side, price, shares, amount, commission)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [run_id, t["ticker"], str(t["date"]), t["side"],
                 t["price"], t["shares"], t["amount"], t["commission"]],
            )
        self.conn.commit()

    def get_backtest_runs(self, limit: int = 20) -> list[dict]:
        """查询历史回测记录。"""
        rows = self.conn.execute(
            "SELECT * FROM backtest_runs ORDER BY id DESC LIMIT ?", [limit]
        ).fetchall()
        return [dict(r) for r in rows]

    def get_trades(self, run_id: int) -> list[dict]:
        """查询某次回测的交易记录。"""
        rows = self.conn.execute(
            "SELECT * FROM trade_logs WHERE run_id = ? ORDER BY trade_date", [run_id]
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        self.conn.close()

    # ── Chat Session CRUD ──

    def create_session(self, session_id: str, messages: list[dict] | None = None) -> dict:
        now = datetime.now().isoformat()
        msgs = messages or []
        self.conn.execute(
            """INSERT INTO chat_sessions (session_id, messages_json, status, created_at, updated_at)
               VALUES (?, ?, 'active', ?, ?)""",
            [session_id, json.dumps(msgs, ensure_ascii=False), now, now],
        )
        self.conn.commit()
        return {"session_id": session_id, "messages": msgs, "status": "active",
                "loop_count": 0, "error_signature": None, "created_at": now, "updated_at": now}

    def get_session(self, session_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM chat_sessions WHERE session_id = ?", [session_id]
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["messages"] = json.loads(d["messages_json"])
        del d["messages_json"]
        if d.get("current_strategy_json"):
            d["current_strategy"] = json.loads(d["current_strategy_json"])
            del d["current_strategy_json"]
        else:
            d["current_strategy"] = None
        return d

    def update_session(self, session_id: str, *, messages: list[dict] | None = None,
                       status: str | None = None, loop_count: int | None = None,
                       error_signature: str | None = None,
                       current_strategy: dict | None = None):
        parts = ["updated_at = ?"]
        vals = [datetime.now().isoformat()]
        if messages is not None:
            parts.append("messages_json = ?")
            vals.append(json.dumps(messages, ensure_ascii=False))
        if status is not None:
            parts.append("status = ?")
            vals.append(status)
        if loop_count is not None:
            parts.append("loop_count = ?")
            vals.append(loop_count)
        if error_signature is not None:
            parts.append("error_signature = ?")
            vals.append(error_signature)
        if current_strategy is not None:
            parts.append("current_strategy_json = ?")
            vals.append(json.dumps(current_strategy, ensure_ascii=False))
        vals.append(session_id)
        self.conn.execute(
            f"UPDATE chat_sessions SET {', '.join(parts)} WHERE session_id = ?", vals
        )
        self.conn.commit()

    def archive_messages(self, session_id: str, messages: list[dict]):
        now = datetime.now().isoformat()
        for msg in messages:
            self.conn.execute(
                """INSERT INTO chat_messages (session_id, role, content, created_at)
                   VALUES (?, ?, ?, ?)""",
                [session_id, msg["role"], msg["content"], now],
            )
        self.conn.commit()

    def get_session_messages(self, session_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT role, content, created_at FROM chat_messages WHERE session_id = ? ORDER BY id",
            [session_id],
        ).fetchall()
        return [dict(r) for r in rows]

    def get_sessions(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT session_id, status, loop_count, created_at, updated_at FROM chat_sessions ORDER BY created_at DESC LIMIT ?",
            [limit],
        ).fetchall()
        return [dict(r) for r in rows]

    # ── LLM Config ──

    def save_llm_config(self, config: dict):
        now = datetime.now().isoformat()
        self.conn.execute(
            """INSERT OR REPLACE INTO llm_config (id, provider, api_key, base_url, model, max_tokens, temperature, updated_at)
               VALUES (1, ?, ?, ?, ?, ?, ?, ?)""",
            [config["provider"], config["api_key"], config.get("base_url"),
             config.get("model", "deepseek-chat"), config.get("max_tokens", 4096),
             config.get("temperature", 0.1), now],
        )
        self.conn.commit()

    def get_llm_config(self) -> dict | None:
        row = self.conn.execute("SELECT * FROM llm_config WHERE id = 1").fetchone()
        if not row:
            return None
        return dict(row)
