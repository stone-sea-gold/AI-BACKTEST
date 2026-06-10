# 实施计划：aiquant 第一期

## 总览

**目标**：交付一个可运行的 CLI + API 回测工具（无 LLM），验证引擎正确性和数据层可靠性。
**范围**：第一期限定沪深300 成分股（约300只），天然过滤退市股避免幸存者偏差。
**计算模式**：所有技术指标由 Compiler 编译为 DuckDB 窗口函数，在 DuckDB 库内完成计算，Python 层零数据搬运。
**预估周期**：按阶段依次推进，阶段间可并行。

---

## 阶段 1：项目骨架与环境搭建（Day 1）

### 任务 1.1：初始化项目结构
- 创建完整目录结构（含 `__init__.py`）
- 创建 `requirements.txt`
- 创建 `.env.example`、`.gitignore`
- 将 `workspace/` 加入 `.gitignore`

### 任务 1.2：配置中心
- 实现 `config/settings.py`：Pydantic BaseSettings（数据路径、DB 路径、日志级别等）
- 实现 `config/logger.py`：统一日志格式

### 任务 1.3：常量定义
- 实现 `utils/constants.py`：A 股交易规则常量
  - 手续费率（佣金、印花税、过户费）
  - 涨跌停限制（10%、ST 5%、科创板 20%）
  - 最小交易单位（100 股）
  - T+1 规则
  - 交易时间段

**产出**：项目骨架搭好，`python -m aiquant` 可运行。

---

## 阶段 2：数据层（Day 2-4）

### 任务 2.1：数据源抽象
- 实现 `store/sources/base.py`：`DataSource` 抽象类，定义统一接口
  - `download_daily(ticker, start_date, end_date) -> pd.DataFrame`
  - `get_all_tickers() -> list[str]`

### 任务 2.2：AData 适配器
- 实现 `store/sources/adata_source.py`
- 实现日线下载、全市场代码列表获取
- 错误重试与日志

### 任务 2.3：BaoStock 适配器（备选）
- 实现 `store/sources/baostock_source.py`
- 同上接口，作为 failover

### 任务 2.4：DuckDB 存储
- 实现 `store/duckdb_store.py`
  - 表结构设计：
    - `daily_kline(ticker, date, open, high, low, close, volume, amount, adj_factor, dividend_cash)` — **close为真实价，adj_factor为复权因子，dividend_cash为每股税前分红**
    - `stock_info(ticker, name, industry, list_date, delist_date)`
    - `csi300_constituents(ticker, in_date, out_date)` — 沪深300历史成分股
    - 前复权价 = `close * adj_factor / MAX(adj_factor) OVER (PARTITION BY ticker)` 在 SQL 中动态计算
  - 数据写入（批量 insert，DuckDB 原生支持 Parquet 直接查询）
  - 查询接口：`get_kline(ticker, start, end)` → 返回含前复权价和分红数据的视图
  - `get_batch_klines(tickers, ...)` → 批量查询用于回测
  - 增量更新逻辑：检查本地最新日期 → 下载缺失区间 → 去重写入
  - 建表 DDL 示例：
    ```sql
    CREATE TABLE daily_kline (
      ticker VARCHAR,
      date DATE,
      open DOUBLE,
      high DOUBLE,
      low DOUBLE,
      close DOUBLE,           -- 真实收盘价 (撮合资金核算用)
      volume DOUBLE,
      amount DOUBLE,
      adj_factor DOUBLE,      -- 复权因子 (计算前复权价用)
      dividend_cash DOUBLE,   -- 每股税前现金分红 (0=当日无派息，用于除权日现金补偿)
      PRIMARY KEY (ticker, date)
    );
    ```

### 任务 2.5：A 股交易日历
- 实现 `store/calendar.py`
  - 从数据源获取交易日历
  - `is_trading_day(date)`、`prev_trading_day(date)`、`next_trading_day(date)`
  - `trading_days_between(start, end)`

### 任务 2.6：数据初始化脚本
- 一键下载沪深300 成分股 3 年日线数据到 DuckDB
- 包含真实收盘价 + 复权因子
- 进度显示，断点续传
- 从 AData 获取沪深300历史成分股列表（须包含调入/调出日期）

**产出**：DuckDB 具备沪深300 约300只标的 × 3年日线数据，含复权因子。

---

## 阶段 3：策略 DSL（Day 5-7）

### 任务 3.1：枚举定义
- 实现 `strategy/conditions.py`
  - `IndicatorType` 枚举：MA, EMA, MACD, RSI, KDJ, BOLL, VOLUME, AMOUNT, TURNOVER, PE, PB 等
  - `ComparatorType` 枚举：>, <, >=, <=, ==, cross_above, cross_below, between
  - `CombineType` 枚举：and, or, not

### 任务 3.2：Pydantic 条件树模型
- 实现 `strategy/models.py`
  - `ConditionNode`：递归树（见 PRD 数据模型）
  - `BuyCondition` / `SellCondition`：组合条件
  - `StopLoss`：止损规则（fixed / trailing / atr / none）
  - `PositionSizing`：仓位规则（fixed_shares / fixed_pct）
  - `StockPool`：标的池（all_a / csi300 / csi500 / custom）
  - `StrategyConfig`：完整策略配置
  - 自定义 validator：递归校验条件树深度限制、参数合理性

### 任务 3.3：标的池
- 实现 `strategy/universe.py`
  - `resolve_stock_pool(pool: StockPool, custom_list: list[str] | None) -> list[str]`
  - 第一期 `StockPool` 枚举仅开放 `csi300` 和 `custom`
  - `all_a` 和 `csi500` 为后续版本预留（枚举定义保留，调用时返回 NotImplemented）
  - 从 `csi300_constituents` 表查询历史上任意日期的成分股列表

### 任务 3.4：编译器（关键变更：DuckDB 作为计算引擎 + 横截面预留）
- 实现 `strategy/compiler.py`

**时间序列指标（v1 全覆盖）**：
  - **`compile_indicator(indicator: IndicatorType, params: dict) -> str`**：
    将技术指标翻译为 DuckDB 窗口函数 SQL 片段
    例：MA(close, 5) → `AVG(close_adj) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW)`

**横截面指标（v1 预留枚举 + SQL模板，v2 对接引擎）**：
  - 新增枚举类型：
    - `RankType`：RANK, DENSE_RANK, PERCENT_RANK, NTILE
    - `CrossSectionIndicator`：RANK(RSI), PERCENTILE(PE), ZSCORE(volume)
  - SQL 模板示例：
    - `RANK() OVER (PARTITION BY date ORDER BY rsi ASC) AS rsi_rank`（横截面排序）
    - `PERCENT_RANK() OVER (PARTITION BY date ORDER BY pe DESC) AS pe_percentile`
  - v1 产物：枚举定义 + SQL 模板注册在 `INDICATOR_REGISTRY` 中
  - v2 产物：条件树叶子节点可引用横截面指标，Compiler 在 CTE 链中嵌套时序窗口函数后再包一层横截面窗口函数

**条件编译**：
  - **`compile_conditions(node: ConditionNode) -> str`**：条件树 → DuckDB WHERE 子句
  - **`build_backtest_query(config: StrategyConfig) -> str`**：
    生成完整 DuckDB SQL——CTE链：
    1. 加载标的池日线数据（含前复权价计算）
    2. 计算所有策略引用的时序指标列（每个指标一个 CTE 或嵌套窗口函数）
    3. [预留] 计算横截面排名列（RANK/PERCENTILE）
    4. 应用买入/卖出条件树 → 标记信号日
    5. 输出信号日列表（ticker, date, signal_type）给引擎消费
  - 支持 AND/OR/NOT 无限递归嵌套
  - **编译器单元测试**：验证生成的 SQL 语法正确、指标公式与已知值一致

**产出**：`StrategyConfig` → `compiler.build_backtest_query()` → DuckDB 执行 → 返回信号日列表。整个计算链在 DuckDB 内闭环。横截面枚举和 SQL 模板就绪但暂不接入引擎循环。

---

## 阶段 4：回测引擎（Day 8-12）

### 任务 4.1：指标规格定义层（角色变更）
- 实现 `engine/indicators.py` —— **不再做数值计算，退化为指标规格定义层**
- 每个指标定义：
  - `name: str`（如 "MA"）
  - `params: list[IndicatorParam]`（如 `[("window", int, 5)]`）
  - `sql_template: str`（DuckDB 窗口函数模板）
  - `validator: Callable`（参数合理性校验）
- 示例：
  ```python
  INDICATOR_REGISTRY = {
      "MA": IndicatorSpec(
          name="MA",
          params=[("window", int)],
          sql_template="AVG({price_col}) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN {window_minus_1} PRECEDING AND CURRENT ROW)",
      ),
      "CROSSOVER": IndicatorSpec(
          name="CROSSOVER",
          sql_template="CASE WHEN {fast_col} > {slow_col} AND LAG({fast_col}) OVER (...) <= LAG({slow_col}) OVER (...) THEN 1 ELSE 0 END",
      ),
      ...
  }
  ```
- Compiler 从此注册表读取 SQL 模板拼接

### 任务 4.2：引擎核心（关键变更：信号-执行分离）
- 实现 `engine/core.py`

**核心循环**（信号-执行分离）：
```
1. DuckDB 全部计算：前复权价 → 指标列 → 条件树过滤 → 输出信号日表
   signals = [
     (ticker, signal_date, signal_type, adjusted_price, real_price),
     ...
   ]

2. 引擎逐日循环：
   for each trading_day T:
     ├─ 卖出检查: 持仓中是否有 T 日的 sell_signal？
     │   └─ 是 → 以 T 日开盘价卖出（一字跌停无法卖出）
     ├─ 买入检查: 是否有 T 日的 buy_signal？（该信号在 T-1 日收盘后生成）
     │   └─ 是 → 以 T 日开盘价买入（一字涨停无法买入）
     ├─ 止损检查: 持仓浮动盈亏达到止损线 → 以 T 日开盘价卖出
     ├─ 分红检查: 持仓中是否有 T 日 dividend_cash > 0 的标的？
     │   └─ 是 → account.cash += shares × dividend_cash × (1 - 红利税率)
     ├─ 更新持仓市值（用真实收盘价 close × 持仓股数）
     └─ 更新账户余额（扣除当日手续费）
```

**关键逻辑**：
- **信号-执行分离**：T 日收盘信号 → T+1 日以开盘价执行（严禁 T 日收盘价撮合 T 日信号）
- **双价格体系**：信号用前复权价 `close_adj`，资金核算用真实收盘价 `close`
- **分红现金补偿**：DuckDB 提供 `dividend_cash`，除权日自动将现金分红（税后）加回账户可用资金，防止除权跳空导致虚假回撤
- **流动性卡点**：一字涨停禁止买入，一字跌停禁止卖出
- **T+1 约束**：当日买入不可当日卖出
- **手续费计算**：佣金（万2.5，最低5元）+ 印花税（千1，仅卖出）+ 过户费（万0.2）
- **涨跌停计算**：主板 ±10%、创业板/科创板 ±20%、ST ±5%
- **仓位管理**：固定股数、固定比例、可用资金限制
- **滑点模型**：统一按开盘价成交（无额外滑点），可选留做后续扩展

### 任务 4.3：绩效计算
- 实现 `engine/performance.py`
  - 累计收益率、年化收益率
  - 夏普比率（无风险利率 2.5% 可配置）
  - 最大回撤及回撤区间
  - 胜率、盈亏比
  - 交易次数、平均持仓天数
  - 月度/年度收益分布
  - 基准对比（沪深 300 买入持有）

### 任务 4.4：引擎集成测试
- 编写 3-5 个已知策略的回测测试用例（均线交叉、MACD金叉等）
- 用少量标的（2-3只）手工验证信号日期、撮合价格、资金计算正确性
- 测试边界情况：一字涨停无法买入、一字跌停无法卖出、T+1 约束

**产出**：可用 CLI 传入策略 JSON 跑回测，输出完整报告。信号-执行分离代码清晰可验证。

---

## 阶段 5：API 服务（Day 13-14）

### 任务 5.1：FastAPI 应用
- 实现 `api/main.py`
  - `POST /backtest`：接收 StrategyConfig JSON → 执行回测 → 返回绩效报告
  - `GET /stocks`：查询可用标的列表
  - `GET /indicators`：查询可用技术指标枚举

### 任务 5.2：Pydantic 请求/响应模型
- 请求模型复用 `strategy/models.py`
- 响应模型定义：`BacktestReport`

### 任务 5.3：Swagger UI 验证
- 启动服务，通过浏览器 Swagger UI 手动测试全流程

**产出**：`uvicorn api.main:app` 启动，Swagger UI 可交互操作回测。

---

## 阶段 6：CLI 与集成（Day 14-15）

### 任务 6.1：CLI 入口
- 实现 `main.py`
  - `python main.py --config strategy.json --output report.json`
  - `python main.py --interactive`：交互式输入策略参数
  - `python main.py --init-data`：初始化数据

### 任务 6.2：架构预留
- 实现 `agent/hub.py`：`LLMProvider` ABC + `LLMHub`（桩实现）
- 实现 `agent/registry.py`：`Tool` ABC + `ToolRegistry`，注册 `BacktestTool`
- 实现 `store/sources/base.py` 中的 `BaseScreener` 抽象（桩实现）

**产出**：第一期完整交付，所有模块可运行，预留接口就绪。

---

## 依赖关系

```
阶段 1 (骨架)
   ↓
阶段 2 (数据层：DuckDB 日线表 + adj_factor + 沪深300成分股)
   ↓
阶段 3 (策略 DSL：枚举 → 条件树 → Compiler 生成 DuckDB 窗口函数 SQL)
   ↓
阶段 4 (引擎：DuckDB 预计算信号 → 引擎逐日循环 → T+1 开盘撮合 → 绩效)
   ↓
阶段 5 (API)
   ↓
阶段 6 (CLI + 预留)
```

## 测试策略

- 每个阶段代码完成后，编写对应的单元测试
- **阶段 3 编译器测试**：验证生成的 DuckDB SQL 语法正确、指标公式值与手工计算一致
- **阶段 4 引擎集成测试**：用 3 只沪深300 标的手工验证信号日期、撮合价格、资金核算
- 使用 pytest，测试数据放在 `tests/fixtures/`

## 两轮发现的六个坑点技术应对方案总结

| # | 坑点 | 核心方案 | 涉及模块 |
|---|------|---------|---------|
| ① | 指标计算双轨 | Python 不碰数值，Compiler 把指标编译为 DuckDB 窗口函数，全链路库内计算 | `strategy/compiler.py` |
| ② | 未来函数 | 信号-执行分离：T日收盘→信号，T+1开盘→撮合。一字涨跌停流动性卡点 | `engine/core.py` |
| ③ | 复权陷阱 | DuckDB 存 close(真实价)+adj_factor(复权因子)，信号用前复权价，核算用真实价 | `store/duckdb_store.py` |
| ④ | 幸存者偏差 | v1 限定沪深300成分股，维护 `csi300_constituents` 历史成分股表 | `strategy/universe.py` |
| ⑤ | 分红资产蒸发 | DuckDB 存 `dividend_cash` 每股分红，引擎除权日自动税后现金加回账户 | `store/duckdb_store.py` `engine/core.py` |
| ⑥ | 横截面盲区 | `RankType`/`CrossSectionIndicator` 枚举 + `RANK() OVER (PARTITION BY date...)` SQL模板预留，v2 对接引擎 | `strategy/conditions.py` `strategy/compiler.py` |

## 交付标准

- [ ] `python main.py --config example.json` 可跑通完整回测
- [ ] `uvicorn api.main:app` 启动后 Swagger UI 可操作
- [ ] 回测结果与已知策略预期一致（误差 < 1%）
- [ ] DuckDB 数据可正确增量更新
- [ ] 条件树可正确翻译为 SQL，深层次嵌套无 bug
- [ ] 所有预留接口已定义（LLM Hub / Tool Registry / BaseScreener）
