# PRD v2: aiquant 第二期 — LLM 接入与智能对话回测

## 1. 版本概述

### 1.1 二期目标
在第一期纯引擎回测工具的基础上，接入 LLM 能力，实现：
- 用户通过自然语言描述策略 → LLM 翻译为结构化 JSON → Pydantic 校验 → 引擎回测
- 异常驱动路由：校验失败时 LLM 自动追问用户补全，最多 3 轮
- Tool Calling 机制：LLM 通过 Function Calling 触发回测，结果返回 LLM 生成解读

### 1.2 一期→二期衔接
一期已就绪的基础设施：
- `StrategyConfig` Pydantic 模型（条件树 + 递归校验）
- `strategy/compiler.py`（条件树 → DuckDB SQL）
- `engine/core.py`（信号-执行分离回测引擎）
- `engine/performance.py`（全量绩效指标）
- `agent/hub.py`（LLMHub 多模型路由桩）
- `agent/registry.py`（ToolRegistry 桩）
- `store/sqlite_store.py`（回测记录持久化）

二期在以上基础上新增 LLM 交互层，不修改一期核心引擎代码。

## 2. 核心架构（二期新增部分）

```
┌─────────────────────────────────────────────────────────────┐
│  接口层                                                      │
│  POST /api/v1/chat  ←→  ChatSession 管理                    │
│  POST /api/v1/config/llm  ←→  LLM 配置持久化                │
├─────────────────────────────────────────────────────────────┤
│  Agent 层（二期核心）                                         │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐    │
│  │  Router      │  │  LLM Hub     │  │  Tool Registry   │    │
│  │  异常驱动路由 │→│  多模型路由    │→│  BacktestTool    │    │
│  │  max_loops=3 │  │  fallback    │  │  (Pydantic→JSON) │    │
│  └─────────────┘  └──────────────┘  └──────────────────┘    │
│       ↕ Pydantic 校验                                        │
│  ┌─────────────┐  ┌──────────────┐                           │
│  │ Prompt 模板  │  │ Session 存储  │                           │
│  │ 动态枚举注入 │  │ SQLite 双表   │                           │
│  └─────────────┘  └──────────────┘                           │
├─────────────────────────────────────────────────────────────┤
│  一期已有的引擎层（不修改）                                    │
│  strategy/compiler → engine/core → engine/performance        │
└─────────────────────────────────────────────────────────────┘
```

## 3. 功能规格

### 3.1 LLM Provider 层

| 功能 | 描述 | 优先级 |
|------|------|--------|
| 多模型支持 | DeepSeek / Claude / OpenAI / 其他，LLMHub 统一路由 | P0 |
| 双协议 | OpenAI 兼容格式（默认）+ Anthropic 协议（自动检测） | P0 |
| 自动 Base URL 映射 | 用户选择厂商 → 自动映射官方 API 地址 | P0 |
| Anthropic 自动检测 | 选择 Claude 厂商 或 key 格式为 `sk-ant-*` → 自动切换 Anthropic 协议 | P0 |
| 「其他」厂商 | 用户选择「其他」时必须手动输入 Base URL | P0 |
| Stream 预留 | 一期非流式，预留 `stream()` 接口 | P1 |

**厂商→Base URL 映射表**：
| 厂商 | Base URL | 协议 |
|------|----------|------|
| DeepSeek | `https://api.deepseek.com/v1` | OpenAI |
| Claude | `https://api.anthropic.com` | Anthropic |
| OpenAI | `https://api.openai.com/v1` | OpenAI |
| 其他 | 用户必填 | 默认 OpenAI |

### 3.2 System Prompt 生成

| 功能 | 描述 | 优先级 |
|------|------|--------|
| 动态枚举注入 | 从 `conditions.py` 的 `IndicatorType`、`ComparatorType`、`CombineType` 自动提取合法值 | P0 |
| 条件树结构说明 | 告知 LLM 分支节点 vs 叶子节点的嵌套规则 | P0 |
| 示例策略 | 1-2 个完整 NL → JSON 示例 | P0 |
| 红线约束 | 禁止编造未定义指标、禁止输出非 JSON 格式 | P0 |
| Prompt 模板文件化 | `agent/prompts/strategy_prompt.py`，可独立维护 | P1 |

### 3.3 对话 Session 管理

| 功能 | 描述 | 优先级 |
|------|------|--------|
| SQLite 双表存储 | `chat_sessions`（运行时主路径）+ `chat_messages`（审计/分析） | P0 |
| Session CRUD | 创建、读取、更新、标记完成/中止 | P0 |
| 滑动窗口压缩 | messages_json 超限时裁剪旧消息，保留锚点 + 摘要 + 近 K 轮 | P0 |
| 错误签名存储 | `error_signature` 字段，加载时直接判断上一轮错误模式 | P0 |
| 消息归档 | 裁剪出窗口的消息追加到 `chat_messages` 分表 | P1 |

**chat_sessions 表**：
```sql
CREATE TABLE chat_sessions (
    session_id TEXT PRIMARY KEY,
    messages_json TEXT NOT NULL,
    current_strategy_json TEXT,
    status TEXT DEFAULT 'active',
    loop_count INTEGER DEFAULT 0,
    error_signature TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

**chat_messages 表（审计用）**：
```sql
CREATE TABLE chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT,
    FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id)
);
```

### 3.4 异常驱动路由

| 功能 | 描述 | 优先级 |
|------|------|--------|
| 主循环 | LLM 生成 → Pydantic 校验 → 失败则追问 → 循环 | P0 |
| 成功终止 | Pydantic 校验通过，立即跳出循环，进入回测 | P0 |
| 失败防御 | max_loops=3，超过则降级提示用户简化表达 | P0 |
| LLM 拒绝终止 | LLM 返回纯文本（非 JSON/非 Tool Call）→ 立即终止，展示文本 | P0 |
| 重复错误检测 | 连续 2 次相同 error_signature → Level 1 改措辞 / Level 2 注入示例 | P0 |
| 用户中止 | 前端发送 abort 信号 → 服务端跳出循环，标记 session=aborted | P0 |

**路由状态机**：
```
用户输入 NL
  ↓
[循环开始] LLM 生成响应
  ├─ 返回 Tool Call (Function Calling)
  │   └─ Pydantic 校验 StrategyConfig
  │       ├─ 通过 → status="success" → 执行回测 → 终止
  │       └─ 失败 → 检查 error_signature
  │           ├─ 新错误 → 追加到 messages → loop_count++ → 继续循环
  │           └─ 重复错误 → Level 1 改措辞 / Level 2 注入示例 → 继续循环
  ├─ 返回纯文本 → status="error" → 展示给用户 → 终止
  └─ loop_count >= 3 → status="error" → 降级提示 → 终止
```

### 3.5 Tool Call 集成

| 功能 | 描述 | 优先级 |
|------|------|--------|
| 自动工具定义 | Pydantic `model_json_schema()` 生成 OpenAI function schema | P0 |
| BacktestTool | 实际调用 `engine/core.run_backtest()` | P0 |
| 结果回传 | 回测结果传回 LLM，生成自然语言解读 | P0 |
| ScreenTool 桩 | 预留选股 Tool 接口 | P1 |

**工具定义自动生成**：
```python
tools = [{
    "type": "function",
    "function": {
        "name": "run_backtest",
        "description": "执行 A 股策略回测",
        "parameters": StrategyConfig.model_json_schema()
    }
}]
```

### 3.6 Chat API

| 功能 | 描述 | 优先级 |
|------|------|--------|
| `POST /api/v1/chat` | 接收 message + session_id，返回 reply + status | P0 |
| session_id 管理 | 新会话时为空，服务端创建后返回 | P0 |
| status 枚举 | `follow_up` / `success` / `error` / `abort` | P0 |
| `POST /api/v1/config/llm` | 保存用户 LLM 配置（厂商/key/base_url） | P0 |
| `GET /api/v1/sessions` | 查询历史 session 列表 | P1 |
| `GET /api/v1/sessions/{id}` | 查询单个 session 详情 | P1 |

**Chat 请求/响应**：
```json
// Request
{
    "message": "帮我测均线金叉",
    "session_id": "abc123"   // 新会话为空
}

// Response
{
    "reply": "需要确认周期，比如5日上穿20日吗？",
    "session_id": "abc123",
    "status": "follow_up"
}
```

## 4. 目录结构（二期新增）

```
aiquant/
├── agent/
│   ├── __init__.py
│   ├── router.py              # ← 二期核心：异常驱动路由循环
│   ├── hub.py                 # ← 二期扩展：实际 LLM 调用逻辑
│   ├── registry.py            # ← 二期扩展：BacktestTool 实际实现
│   ├── session.py             # ← 二期新增：ChatSession 管理
│   ├── prompts/
│   │   ├── __init__.py
│   │   └── strategy_prompt.py # ← 二期新增：System Prompt 动态生成
│   └── schemas.py             # ← 二期新增：Chat 请求/响应模型
├── providers/                 # ← 二期新增
│   ├── __init__.py
│   ├── base.py                # Provider 配置基类
│   ├── deepseek_provider.py   # DeepSeek (OpenAI 兼容)
│   ├── claude_provider.py     # Claude (Anthropic 协议)
│   └── openai_provider.py     # OpenAI (原生)
├── store/
│   ├── sqlite_store.py        # ← 二期扩展：新增 chat_sessions/chat_messages 表
│   └── ...
├── api/
│   ├── __init__.py
│   ├── main.py                # ← 二期扩展：新增 chat/config 端点
│   └── chat.py                # ← 二期新增：Chat 路由逻辑
└── ...
```

## 5. 配置模型

### 5.1 LLM 配置（.env 或用户面板输入）

```python
class LLMConfig(BaseModel):
    provider: Literal["deepseek", "claude", "openai", "other"] = "deepseek"
    api_key: str
    base_url: str | None = None       # 留空则自动映射
    model: str = "deepseek-v4-flash"  # 默认模型
    max_tokens: int = 4096
    temperature: float = 0.1          # 低温度保证 JSON 输出稳定
```

### 5.2 路由配置

```python
class RouterConfig(BaseModel):
    max_loops: int = 3
    sliding_window_max_messages: int = 20
    duplicate_error_threshold: int = 2
```

## 6. 性能与约束

- **单次对话延迟**：非流式，LLM 响应 + Pydantic 校验 < 10 秒
- **Session 存储**：SQLite 单表，单 session messages_json < 100KB
- **并发**：单进程，不做并发处理（一期范围）
- **Token 消耗**：System Prompt ~2000 tokens + 对话历史 ~2000 tokens，单次调用 < 5000 tokens
