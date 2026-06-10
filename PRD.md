# PRD: aiquant — A股智能回测 Agent

## 1. 产品概述

### 1.1 一句话定位
一个通过自然语言交互、为 A 股投资者提供专业级策略回测与每日选股服务的智能 Agent 系统。

### 1.2 目标用户
- **核心用户**：A 股散户投资者，懂策略逻辑但不想写代码
- **扩展用户**：专业量化投资者，需要快速验证策略想法

### 1.3 核心价值
- 用自然语言描述策略 → 自动翻译为结构化回测 → 输出绩效报告
- 每日选股 + 历史胜率验证 → 辅助交易决策
- 散户友好的交互界面 + 专业量化的底层能力

## 2. 产品架构

### 2.1 五层架构

```
接口层     CLI / FastAPI Swagger / 未来 Web UI
              │
Agent 层    LLM Hub (多LLM) + Router (异常驱动路由) + Tool Registry
              │
策略层      Pydantic 条件树 + Compiler (条件树 → DuckDB 窗口函数SQL)
              │
引擎层      T日信号/前复权 → T+1开盘撮合/真实价 → 资金管理 → 绩效
              │
存储层      DuckDB (行情+因子全在库内计算) + SQLite (配置/日志)
              │
数据源      AData (主) + BaoStock (备) → 本地化存储
```

### 2.2 核心链路

**链路一：策略回测（直通车）**
```
用户输入 NL → LLM 翻译 → Pydantic 校验 ─┬─ 通过 → Compiler(条件→DuckDB窗口函数) → DuckDB内执行 → 报告
                                         └─ 失败 → LLM 追问用户 → 重试
```

**链路二：今日选股 + 历史验证**
```
用户输入 NL → 选股 LLM → 筛选今日候选股 → 回测引擎逐股回溯 → 胜率排名
```

## 3. 功能规格

### 3.1 第一期（纯引擎 + API，无 LLM）

| 功能 | 描述 | 优先级 |
|------|------|--------|
| 数据层 | DuckDB 日线建表（含close真实价 + adj_factor复权因子）、AData/BaoStock 数据下载与增量更新、A 股交易日历 | P0 |
| 策略模型 | Pydantic 条件树（AND/OR/NOT 递归嵌套 + 枚举指标叶子节点） | P0 |
| 编译器 | 条件树 → DuckDB 窗口函数 SQL（AVG() OVER ...），指标计算全在 DuckDB 库内完成，Python 不参与数值计算 | P0 |
| 回测引擎 | 信号-执行分离：T日收盘计算信号 → T+1开盘价撮合（含一字涨跌停流动性卡点）、T+1约束、资金管理 | P0 |
| 绩效指标 | 累计/年化收益、夏普比率、最大回撤、胜率、盈亏比、交易次数 | P0 |
| 标的池 | 第一期限沪深300成分股，规避幸存者偏差，后续版本扩展全市场 | P0 |
| API 服务 | FastAPI + Swagger UI，`POST /backtest` 端点 | P0 |
| CLI 入口 | `python main.py --config strategy.json` | P1 |
| 架构预留 | LLM Hub / Tool Registry / BaseScreener 抽象接口定义 | P1 |

### 3.2 第二期（LLM 接入）

| 功能 | 描述 | 优先级 |
|------|------|--------|
| LLM Hub | 多 LLM Provider 统一抽象（Claude / DeepSeek / OpenAI） | P0 |
| 异常驱动路由 | 用户输入 → LLM → Pydantic 校验 → 追问闭环 | P0 |
| Tool Registry | BacktestTool / ScreenTool 注册与调用 | P0 |
| 对话上下文管理 | 完整对话历史维护，防止 LLM 失忆 | P0 |
| 流式输出 | LLM 思考过程实时展示 | P1 |

### 3.3 第三期（选股 + 进阶）

| 功能 | 描述 | 优先级 |
|------|------|--------|
| 每日选股链路 | 选股 LLM → 因子筛选 → 候选列表 → 逐股回测 → 胜率排名 | P0 |
| 基本面分析 | LLM 读取财报进行基本面评分（BaseScreener v2） | P1 |
| Web UI | React/Vue 前端界面 | P1 |
| 报告可视化 | 收益曲线图、回撤图、交易分布图 | P1 |
| 策略分享 | 策略 JSON 导出/导入、社区分享 | P2 |

## 4. 核心数据模型

### 4.1 条件树（策略 DSL 核心）

```python
class ConditionNode(BaseModel):
    """递归条件树"""
    operator: Literal["and", "or", "not"] | None = None
    conditions: list[ConditionNode] = []
    # 叶子节点
    indicator: IndicatorType | None = None  # 枚举：MA, MACD, VOLUME, RSI, BOLL...
    comparator: ComparatorType | None = None  # >, <, >=, <=, cross_above, cross_below
    value: float | str | None = None
```

### 4.2 存储层

| 存储 | 用途 | 技术 |
|------|------|------|
| DuckDB | 日线 K 线（含 close 真实价 + adj_factor 复权因子 + dividend_cash 每股分红）、财务因子、绩效结果 | 列式 OLAP |
| SQLite | 用户回测配置、订单日志、交易信号记录 | 行式 OLTP |
| Parquet | 行情文件物理存储（workspace/klines/） | 列式文件 |

**价格字段设计（关键）**：
- `close`：真实收盘价（用于资金核算和持仓市值）
- `adj_factor`：复权因子（用于动态计算前复权价跑策略信号）
- `dividend_cash`：每股税前现金分红（0 表示当日无派息，用于除权日现金补偿）
- 前复权价 = close × adj_factor / last_adj_factor，仅在 DuckDB 查询内动态计算，不额外存储

### 4.3 数据源策略

- **首选**：AData（多源融合，自动故障切换，免费）
- **备选**：BaoStock（稳定，无需注册，文档规范）
- **数据覆盖**：A 股全市场日线/周线/月线 K 线、复权因子、基本面数据
- **更新策略**：定时增量更新（交易日收盘后），避免重复下载

### 4.4 核心设计原则（防"硬伤"）

**原则一：DuckDB 既是存储也是计算引擎（防「指标计算双轨」）**
- 所有技术指标（MA、MACD、RSI、BOLL 等）由 Compiler 直接编译为 DuckDB 窗口函数
  - 例：`AVG(close_adj) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS MA5`
- `engine/indicators.py` 退化为「指标规格定义层」，定义每个指标的参数、公式和 SQL 模板，不做数值计算
- Python 层零数据拷贝，全链路在 DuckDB 内完成

**原则二：信号-执行分离（防「未来函数」）**
- T 日收盘后：基于 T 日收盘价计算指标 → 生成买入/卖出信号
- T+1 日开盘：以开盘价（open）执行 T 日生成的信号
- 流动性卡点：一字涨停（open == high == pre_close_limit_up）禁止买入，一字跌停禁止卖出
- 严禁直接以 T 日收盘价撮合 T 日信号

**原则三：双价格体系（防「复权陷阱」）**
- 策略信号计算：使用**前复权价格** `close × (adj_factor / last_adj_factor)`
- 账户资金核算：使用**真实收盘价** `close`
- DuckDB 存储两种价格，SQL 查询内动态转换

**原则四：第一期限定沪深300（防「幸存者偏差」）**
- v1 标的池仅限沪深300指数成分股，天然过滤退市股
- v2 扩展到全市场时，需维护历史成分股列表，支持 point-in-time 标的池

**原则五：分红现金补偿（防「真实价资产核算漏洞」）**
- 真实收盘价在除权除息日会发生跳空下跌（如10派5元，股价从10元跳到9.5元）
- DuckDB 存储 `dividend_cash`（每股税前现金分红）列，不为0时表示当日发生现金分红
- 引擎在 T 日收盘更新持仓市值后，检查 `dividend_cash > 0`，执行：
  `account.cash += position.shares × dividend_cash × (1 - 红利税率)`
- 确保长线持有策略不会被分红除权导致的虚假回撤影响
- 送转股场景（adj_factor 变化但 dividend_cash=0）：需同步调整持仓股数，第一期可暂缓（沪深300送转股低频）

**原则六：横截面计算预留（防「DSL 成为时序盲区」）**
- 当前 Compiler 的窗口函数以 `PARTITION BY ticker ORDER BY date` 为主（纵向时序）
- 需同时支持 `PARTITION BY date ORDER BY indicator` 的横截面计算（横向排序）
- 典型场景：「买沪深300里RSI最低的前10只」「PE后20%分位的标的」
- 在 `IndicatorType` 枚举中预留 `RankType` 子枚举（RANK, PERCENTILE, ZSCORE）
- Compiler 在 CTE 链中嵌套横截面窗口函数：`RANK() OVER (PARTITION BY date ORDER BY rsi ASC)`
- v1 仅实现枚举定义和 SQL 模板注册，引擎集成延后到 v2 轮动策略

## 5. 架构预留点

### 5.1 LLM Hub

```python
class LLMProvider(ABC):
    async def generate(self, messages: list[dict], tools: list | None = None) -> LLMResponse
    async def stream(self, messages: list[dict]) -> AsyncIterator[str]

class LLMHub:
    providers: dict[str, LLMProvider]
    routing_strategy: Literal["primary_only", "fallback", "ensemble"]
    async def route(self, task: LLMTask) -> LLMResponse
```

### 5.2 Tool Registry

```python
class Tool(ABC):
    name: str
    description: str
    async def execute(self, params: dict) -> ToolResult

class BacktestTool(Tool): ...
class ScreenTool(Tool): ...
class ExplainTool(Tool): ...
```

### 5.3 BaseScreener

```python
class BaseScreener(ABC):
    async def screen(self, conditions: ConditionNode) -> list[str]

class FactorScreener(BaseScreener):
    """v1: DuckDB SQL 因子选股"""

class LLMScreener(BaseScreener):
    """v2: LLM 基本面选股（预留）"""
```

## 6. 目录结构

```
aiquant/
├── config/               # 全局配置中心
│   ├── settings.py       # Pydantic BaseSettings
│   └── logger.py         # 日志配置
├── agent/                # LLM 交互层 (第一期: 留接口/桩)
│   ├── __init__.py
│   ├── router.py         # 异常驱动路由循环
│   ├── hub.py            # LLM Hub 抽象 (多 Provider)
│   ├── registry.py       # Tool Registry
│   ├── prompts/          # System prompts
│   └── schemas.py        # LLM 输入/输出格式
├── strategy/             # 策略 DSL
│   ├── models.py         # Pydantic 策略/条件树模型
│   ├── conditions.py     # 枚举条件 (MA, MACD, VOLUME 等)
│   ├── universe.py       # 标的池筛选规则
│   └── compiler.py       # 条件树 → SQL/执行计划
├── engine/               # 回测引擎
│   ├── core.py           # 核心撮合循环、资金管理
│   ├── indicators.py     # 技术指标底层实现
│   └── performance.py    # 绩效计算
├── store/                # 数据存储层
│   ├── duckdb_store.py   # DuckDB 行情/因子查询
│   ├── sqlite_store.py   # SQLite 配置/日志
│   ├── sources/          # 数据源适配器
│   │   ├── base.py       # 数据源抽象
│   │   ├── adata_source.py
│   │   └── baostock_source.py
│   └── calendar.py       # A 股交易日历
├── utils/                # 通用工具
│   ├── helpers.py        # 类型转换、时间戳处理
│   └── constants.py      # 全局常量 (手续费率、涨跌停等)
├── api/                  # FastAPI 服务
│   ├── __init__.py
│   └── main.py
├── main.py               # CLI/服务启动入口
├── requirements.txt
├── .env.example          # 环境变量模板
└── workspace/            # 数据目录 (.gitignore)
    ├── klines/           # Parquet 行情文件
    └── aiquant.db        # SQLite 数据库
```

## 7. 性能与约束

- **数据量**：沪深300 约300标的，日线每标的约250条/年，3年约22.5万行（第一期）
- **回测速度**：沪深300 全量 3年日线回测应在 10 秒内完成
- **数据更新**：增量更新，避免重复下载，每天收盘后自动同步最近交易日
- **存储空间**：3年沪深300日线约 50MB

## 8. 开放性问题（第二期再细化）

- LLM 的 prompt 工程与幻觉控制策略
- 多轮对话中的上下文窗口管理
- A 股实时行情的推送机制
- 用户注册/策略持久化存储
- 回测结果的缓存策略
