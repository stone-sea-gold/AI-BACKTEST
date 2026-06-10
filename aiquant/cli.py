"""CLI 公共逻辑，main.py 和 __main__.py 共用。"""

from __future__ import annotations

import argparse
import json

from aiquant.config.logger import logger


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="aiquant — A股智能回测 Agent")
    subparsers = parser.add_subparsers(dest="command")

    # 回测命令
    backtest_parser = subparsers.add_parser("backtest", help="执行策略回测")
    backtest_parser.add_argument("--config", required=True, help="策略配置 JSON 文件路径")
    backtest_parser.add_argument("--output", default="report.json", help="输出报告路径")

    # 数据初始化命令
    init_parser = subparsers.add_parser("init-data", help="初始化沪深300数据")
    init_parser.add_argument("--years", type=int, default=3, help="下载几年的数据 (默认3)")
    init_parser.add_argument("--source", choices=["adata", "baostock"], default="adata", help="数据源")

    # 版本
    subparsers.add_parser("version", help="显示版本信息")

    return parser


def run(args: argparse.Namespace) -> None:
    if args.command == "version":
        logger.info("aiquant v0.1.0")

    elif args.command == "backtest":
        from aiquant.engine.core import run_backtest
        from aiquant.engine.performance import calculate_performance, format_report
        from aiquant.store.duckdb_store import DuckDBStore
        from aiquant.store.sqlite_store import SQLiteStore
        from aiquant.strategy.models import StrategyConfig

        with open(args.config, encoding="utf-8") as f:
            config_data = json.load(f)
        config = StrategyConfig(**config_data)

        store = DuckDBStore()
        result = run_backtest(config, store)
        report = calculate_performance(result)
        print(format_report(report))

        # 保存到 SQLite
        try:
            sq = SQLiteStore()
            run_id = sq.save_backtest_run(
                config.name, json.dumps(config_data, ensure_ascii=False),
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
            sq.save_trades(run_id, [
                {"ticker": t.ticker, "date": t.date, "side": t.side,
                 "price": t.price, "shares": t.shares, "amount": t.amount,
                 "commission": t.commission}
                for t in result.trades
            ])
            sq.close()
            logger.info(f"回测记录已保存到 SQLite (run_id={run_id})")
        except Exception as e:
            logger.warning(f"保存到 SQLite 失败: {e}")

        # 保存 JSON 报告
        if args.output:
            report_data = {
                "total_return": report.total_return,
                "annual_return": report.annual_return,
                "max_drawdown": report.max_drawdown,
                "sharpe_ratio": report.sharpe_ratio,
                "win_rate": report.win_rate,
                "total_trades": report.total_trades,
                "final_value": report.final_value,
            }
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report_data, f, indent=2, ensure_ascii=False)
            logger.info(f"报告已保存到 {args.output}")

        store.close()

    elif args.command == "init-data":
        from aiquant.store.init_data import init_data
        init_data(years=args.years, source=args.source)

    else:
        build_parser().print_help()


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    run(args)
