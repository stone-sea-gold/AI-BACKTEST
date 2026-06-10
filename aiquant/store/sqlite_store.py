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
