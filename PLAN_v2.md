# 实施计划：aiquant 第二期 — LLM 接入

## 总览

**目标**：在一期引擎基础上接入 LLM，实现自然语言→策略翻译→回测执行的完整闭环。
**基础**：一期已完成引擎、编译器、数据层、API、CLI，本计划不修改一期核心代码。
**新增**：LLM Provider、异常驱动路由、Tool Calling、Session 管理、Chat API。

---

## 阶段 2.1：LLM Provider 实现（Day 1-2）

### 任务 2.1.1：Provider 基类与配置
- 新建 `providers/base.py`
  - `LLMConfig` Pydantic 模型：provider / api_key / base_url / model / max_tokens / temperature
  - Base URL 自动映射逻辑：
    ```
    provider → base_url 映射：
    deepseek → https://api.deepseek.com/v1
    claude   → https://api.anthropic.com
    openai   → https://api.openai.com/v1
    other    → 用户必填 base_url
    ```
  - Anthropic 自动检测：`provider == "claude"` 或 `api_key.startswith("sk-ant-")` → 强制 Anthropic 协议

### 任务 2.1.2：DeepSeek Provider
- 新建 `providers/deepseek_provider.py`
- 继承 `LLMProvider` ABC
- 使用 `openai` Python SDK，`base_url` 指向 DeepSeek
- 实现 `generate(messages, tools)` → `LLMResponse`
- 实现 `stream(messages)` → `AsyncIterator[str]`（桩实现，一期非流式）

### 任务 2.1.3：Claude Provider
- 新建 `providers/claude_provider.py`
- 使用 `anthropic` Python SDK
- 实现消息格式转换：OpenAI messages 格式 ↔ Anthropic messages 格式
- 实现 Tool Call 格式转换：OpenAI function_call ↔ Anthropic tool_use
- 实现 `generate(messages, tools)` → `LLMResponse`

### 任务 2.1.4：OpenAI Provider
- 新建 `providers/openai_provider.py`
- 使用 `openai` Python SDK，原生 OpenAI API
- 实现 `generate(messages, tools)` → `LLMResponse`

### 任务 2.1.5：LLMHub 扩展
- 修改 `agent/hub.py`
- `LLMHub.__init__` 接受 `LLMConfig`，自动创建对应 Provider
- `route()` 方法实现 fallback 策略：主模型失败 → 降级到下一个

**产出**：`LLMHub` 可根据配置自动初始化 DeepSeek/Claude/OpenAI Provider，调用 `generate()` 返回 `LLMResponse`。

---

## 阶段 2.2：System Prompt 动态生成（Day 2）

### 任务 2.2.1：Prompt 模板
- 新建 `agent/prompts/strategy_prompt.py`
- 实现 `build_system_prompt()` → `str`
- 动态注入内容：
  1. **角色定义**：「你是一个 A 股策略翻译助手，将用户的自然语言策略描述转换为结构化 JSON」
  2. **枚举清单**：从 `IndicatorType`、`ComparatorType`、`CombineType` 自动提取所有合法值
  3. **条件树结构**：说明分支节点（operator+conditions）vs 叶子节点（indicator+comparator+value+params）
  4. **示例策略**：1-2 个完整的 NL → JSON 示例（含条件树嵌套）
  5. **红线约束**：禁止编造未定义指标、必须输出合法 JSON、不要输出解释性文本

### 任务 2.2.2：Prompt 单元测试
- 验证 `build_system_prompt()` 包含所有 `IndicatorType` 枚举值
- 验证包含 `ComparatorType` 所有值
- 验证示例 JSON 可被 `StrategyConfig` 正确解析

**产出**：`build_system_prompt()` 返回完整的 system prompt 字符串，所有枚举值动态注入。

---

## 阶段 2.3：Session 存储（Day 2-3）

### 任务 2.3.1：Session 数据模型
- 新建 `agent/session.py`
- `ChatSession` dataclass：
  ```python
  @dataclass
  class ChatSession:
      session_id: str
      messages: list[dict]       # 从 messages_json 反序列化
      current_strategy: dict | None
      status: str                # active / completed / aborted
      loop_count: int
      error_signature: str | None
      created_at: str
      updated_at: str
  ```

### 任务 2.3.2：SQLite 表扩展
- 修改 `store/sqlite_store.py`
- 新增 `chat_sessions` 表和 `chat_messages` 表（见 PRD v2 表结构）
- 实现 CRUD 方法：
  - `create_session(session_id, messages) -> ChatSession`
  - `get_session(session_id) -> ChatSession | None`
  - `update_session(session_id, messages, status, loop_count, error_signature)`
  - `archive_messages(session_id, messages)` — 裁剪消息追加到 chat_messages 分表
  - `get_session_messages(session_id) -> list[dict]` — 查询审计消息

### 任务 2.3.3：滑动窗口压缩
- 在 `session.py` 中实现 `compress_messages(messages, max_messages) -> list[dict]`
- 保留策略：
  - 第一条 system prompt 始终保留（锚点）
  - 最近 K 轮对话保留
  - 中间部分压缩为摘要消息：`{"role": "system", "content": "（历史摘要：用户讨论了均线金叉策略，已确认参数为5/20）"}`
- 被裁剪的消息调用 `archive_messages()` 归档

**产出**：`ChatSession` 完整 CRUD，滑动窗口压缩可用。

---

## 阶段 2.4：异常驱动路由核心（Day 3-5）

### 任务 2.4.1：Router 实现
- 新建 `agent/router.py`
- 实现核心循环 `process_message(session_id, user_message) -> ChatResponse`

**伪代码**：
```python
async def process_message(session_id: str, user_message: str) -> ChatResponse:
    session = get_or_create_session(session_id)
    session.messages.append({"role": "user", "content": user_message})

    while session.loop_count < MAX_LOOPS:
        # 1. 调用 LLM
        system_prompt = build_system_prompt()
        response = await hub.route(
            messages=[{"role": "system", "content": system_prompt}] + session.messages,
            tools=get_tool_definitions()
        )

        # 2. 检查 LLM 响应类型
        if response.tool_calls:
            # LLM 输出了 Tool Call → 提取 StrategyConfig JSON
            strategy_json = extract_strategy_from_tool_call(response.tool_calls)
            session.messages.append({"role": "assistant", "tool_calls": response.tool_calls})

            # 3. Pydantic 校验
            try:
                config = StrategyConfig(**strategy_json)
                session.status = "completed"
                session.current_strategy = strategy_json
                save_session(session)

                # 4. 执行回测
                result = run_backtest(config, store)
                report = calculate_performance(result)

                return ChatResponse(
                    reply=format_report(report),
                    session_id=session.session_id,
                    status="success"
                )
            except ValidationError as e:
                # 校验失败 → 错误签名检测
                error_sig = extract_error_signature(e)
                if error_sig == session.error_signature:
                    # 重复错误 → 升级策略
                    error_msg = build_escalation_message(e, session.loop_count)
                else:
                    error_msg = build_error_message(e)

                session.messages.append({"role": "system", "content": error_msg})
                session.error_signature = error_sig
                session.loop_count += 1
                save_session(session)
                continue

        elif response.content:
            # LLM 返回纯文本 → 拒绝/解释
            session.status = "aborted"
            save_session(session)
            return ChatResponse(
                reply=response.content,
                session_id=session.session_id,
                status="error"
            )

    # 超过 max_loops
    session.status = "aborted"
    save_session(session)
    return ChatResponse(
        reply="抱歉，无法将您的策略转化为标准配置，请简化表达后重试。",
        session_id=session.session_id,
        status="error"
    )
```

### 任务 2.4.2：错误签名提取
- 实现 `extract_error_signature(error: ValidationError) -> str`
- 签名算法：取 Pydantic 错误中第一个错误的 `(field, type)` 元组的 hash
- 例：`("buy_condition.condition.conditions.0.value", "float_parsing")` → `"value_float_parsing"`

### 任务 2.4.3：升级策略
- Level 1（重复错误首次）：改变反馈措辞，强调具体约束
  - 例：原始错误「value 必须是数字」→ 升级「value 字段必须是浮点数，如 10.0 或 15.5，不能是字符串」
- Level 2（重复错误第二次）：丢弃部分历史，注入正确示例
  - 在 messages 中追加一条 system 消息，包含一个该字段的正确 JSON 示例

### 任务 2.4.4：Router 单元测试
- 测试 Pydantic 校验通过 → 立即终止
- 测试 max_loops 超限 → 降级提示
- 测试 LLM 纯文本回复 → 终止
- 测试重复错误 → 升级策略

**产出**：`process_message()` 完整实现，异常驱动路由可运行。

---

## 阶段 2.5：Tool Call 集成（Day 4-5）

### 任务 2.5.1：工具定义自动生成
- 实现 `agent/registry.py` 中的 `get_tool_definitions() -> list[dict]`
- 使用 `StrategyConfig.model_json_schema()` 自动生成 OpenAI function schema
- 处理 Pydantic schema → OpenAI parameters 格式的兼容性（如 `anyOf` → `type: object`）

### 任务 2.5.2：BacktestTool 实际实现
- 修改 `agent/registry.py` 中的 `BacktestTool`
- `execute()` 方法实际调用 `engine/core.run_backtest()`
- 返回 `ToolResult(success=True, data={...绩效指标...})`

### 任务 2.5.3：Tool Call 响应格式转换
- 实现 OpenAI ↔ Anthropic Tool Call 格式互转
- OpenAI: `{"tool_calls": [{"function": {"name": "...", "arguments": "..."}}]}`
- Anthropic: `{"content": [{"type": "tool_use", "name": "...", "input": {...}}]}`

**产出**：`get_tool_definitions()` 返回合法的 OpenAI tools schema，`BacktestTool` 可实际执行回测。

---

## 阶段 2.6：Chat API 端点（Day 5-6）

### 任务 2.6.1：Chat 请求/响应模型
- 新建 `agent/schemas.py`
- `ChatRequest`：message (str) + session_id (str | None)
- `ChatResponse`：reply (str) + session_id (str) + status (Literal["follow_up", "success", "error", "abort"])

### 任务 2.6.2：Chat 路由
- 新建 `api/chat.py`
- 实现 `POST /api/v1/chat` 端点
- 调用 `router.process_message()`
- 返回 `ChatResponse`

### 任务 2.6.3：LLM 配置端点
- 实现 `POST /api/v1/config/llm`
- 接收 `LLMConfig` JSON → 保存到 `.env` 或 SQLite
- 实现 `GET /api/v1/config/llm` → 返回当前配置（API Key 脱敏）

### 任务 2.6.4：Session 查询端点
- 实现 `GET /api/v1/sessions` → 查询 session 列表
- 实现 `GET /api/v1/sessions/{session_id}` → 查询单个 session 详情

### 任务 2.6.5：注册到 FastAPI
- 修改 `api/main.py`，引入 `api/chat.py` 路由

**产出**：Swagger UI 可交互测试 `/api/v1/chat` 端点。

---

## 阶段 2.7：集成测试（Day 6-7）

### 任务 2.7.1：端到端测试
- 测试完整链路：NL 输入 → LLM 翻译 → Pydantic 校验 → 回测执行 → 报告返回
- 测试用例：
  1. 「5日均线上穿20日均线买入，下穿卖出」→ 一轮成功
  2. 「帮我测均线金叉」→ 触发追问 → 用户补全 → 成功
  3. 「帮我测一个不存在的指标」→ LLM 拒绝 → 终止
  4. 连续 3 轮 Pydantic 校验失败 → 降级提示

### 任务 2.7.2：Provider 切换测试
- 测试 DeepSeek / Claude / OpenAI 三种 Provider 的调用
- 测试 fallback：主模型失败 → 自动降级

### 任务 2.7.3：Session 持久化测试
- 测试 session 创建、更新、状态变更
- 测试滑动窗口压缩：超过 20 条消息后自动裁剪
- 测试消息归档：裁剪的消息出现在 chat_messages 分表

**产出**：所有集成测试通过，端到端链路可用。

---

## 依赖关系

```
阶段 2.1 (Provider) ──┐
阶段 2.2 (Prompt)   ──┼──→ 阶段 2.4 (路由核心) ──→ 阶段 2.6 (Chat API) ──→ 阶段 2.7 (测试)
阶段 2.3 (Session)  ──┤                              ↑
阶段 2.5 (Tool Call)──┘                              │
                                                     └── 阶段 2.6 依赖 2.4 + 2.5
```

2.1 / 2.2 / 2.3 / 2.5 可并行开发，2.4 是核心串联点。

## 测试策略

- 每个阶段编写对应的单元测试
- 阶段 2.4 路由核心需 mock LLM 响应进行测试（不实际调用 API）
- 阶段 2.7 使用真实 LLM API 进行端到端测试（可选 DeepSeek，成本最低）

## 交付标准

- [ ] `POST /api/v1/chat` 端点可用，Swagger UI 可交互
- [ ] 用户输入 NL → LLM 翻译 → Pydantic 校验 → 回测执行 → 返回报告
- [ ] 异常驱动路由：校验失败时自动追问，max_loops=3
- [ ] LLM 返回纯文本时正确终止
- [ ] Session 持久化到 SQLite，重启后可恢复
- [ ] 滑动窗口压缩正确裁剪旧消息
- [ ] Tool Call 通过 Function Calling 触发，Pydantic schema 自动生成
- [ ] DeepSeek / Claude / OpenAI 三种 Provider 可切换
- [ ] LLM 配置 API 可用（保存/读取厂商/key/base_url）
