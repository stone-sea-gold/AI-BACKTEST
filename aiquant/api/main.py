"""FastAPI 服务。"""

from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from aiquant.engine.core import run_backtest
from aiquant.engine.performance import calculate_performance
from aiquant.store.duckdb_store import DuckDBStore
from aiquant.store.sqlite_store import SQLiteStore
from aiquant.strategy.conditions import IndicatorType
from aiquant.strategy.models import StrategyConfig

app = FastAPI(title="aiquant", description="A股智能回测 Agent API", version="0.1.0")

store = DuckDBStore()
sqlite_store = SQLiteStore()


@app.get("/", include_in_schema=False)
def root():
    """重定向到 Swagger UI。"""
    return RedirectResponse(url="/docs")


class BacktestRequest(StrategyConfig):
    pass


class BacktestResponse(BaseModel):
    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe_ratio: float
    win_rate: float
    total_trades: int
    final_value: float
    run_id: int | None = None


@app.post("/backtest", response_model=BacktestResponse)
def backtest(req: BacktestRequest):
    """执行策略回测。"""
    try:
        result = run_backtest(req, store)
        report = calculate_performance(result)

        # 保存到 SQLite
        run_id = None
        try:
            run_id = sqlite_store.save_backtest_run(
                req.name, json.dumps(req.model_dump(), ensure_ascii=False),
                {
                    "total_return": report.total_return,
                    "annual_return": report.annual_return,
                    "max_drawdown": report.max_drawdown,
                    "sharpe_ratio": report.sharpe_ratio,
                    "win_rate": report.win_rate,
                    "total_trades": report.total_trades,
                    "final_value": report.final_value,
                },
            )
            sqlite_store.save_trades(run_id, [
                {"ticker": t.ticker, "date": t.date, "side": t.side,
                 "price": t.price, "shares": t.shares, "amount": t.amount,
                 "commission": t.commission}
                for t in result.trades
            ])
        except Exception:
            pass

        return BacktestResponse(
            total_return=report.total_return,
            annual_return=report.annual_return,
            max_drawdown=report.max_drawdown,
            sharpe_ratio=report.sharpe_ratio,
            win_rate=report.win_rate,
            total_trades=report.total_trades,
            final_value=report.final_value,
            run_id=run_id,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/stocks")
def get_stocks():
    """查询可用标的列表（沪深300成分股）。"""
    tickers = store.get_csi300_tickers()
    return {"tickers": tickers, "count": len(tickers)}


@app.get("/indicators")
def get_indicators():
    """查询可用技术指标枚举。"""
    return {"indicators": [i.value for i in IndicatorType]}


@app.get("/history")
def get_history(limit: int = 20):
    """查询历史回测记录。"""
    return {"runs": sqlite_store.get_backtest_runs(limit)}


@app.get("/history/{run_id}/trades")
def get_trades(run_id: int):
    """查询某次回测的交易记录。"""
    trades = sqlite_store.get_trades(run_id)
    if not trades:
        raise HTTPException(status_code=404, detail=f"run_id={run_id} 不存在或无交易记录")
    return {"run_id": run_id, "trades": trades}
