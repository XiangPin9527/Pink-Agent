# AI Agent Engine

基于 LangGraph 的智能多级 Agent 编排引擎，集成多级记忆系统和异步消息队列，为业务系统提供 AI 对话能力。

## 系统架构
![alt text](image-1.png)


## 核心特性

### 智能路由编排
- **自动分类**: Router 节点根据消息特征自动判断任务复杂度
- **简单任务**: 单轮问答、翻译、简单查询 → 直接由 simple_handler 处理
- **复杂任务**: 多步骤执行、多工具协同 → 由 Analyzer → Executor → Judge → Reporter 链路处理
- **代码审计任务**: 代码安全审计、漏洞检测 → CodeRetriever → VulnerabilityAnalyzer → AuditReporter
- **反思循环**: Judge 评估不通过时自动返回 Analyzer 重新规划（最多 3 次迭代）

### 多级记忆系统
- **短期记忆（动态压缩）**:
  - 消息 < 30 条：全量携带
  - 消息 >= 30 条：MQ 异步压缩，生成摘要
  - 后续携带：`[摘要]` + [最新消息]
  - 保留策略：始终保留最新 20 条不压缩
- **长期记忆**: PostgreSQL + pgvector 存储用户画像、偏好、项目背景
- **异步提取**: RabbitMQ 驱动，每 10 条用户消息触发一次长期记忆提取
- **用户指令记忆**: Redis (TTL 7天) + PostgreSQL 双级存储，支持用户定制化约束

### 两级 Checkpoint
- **Redis 同步写入**: 微秒级响应，保障快速读取
- **PostgreSQL 异步持久化**: MQ 投递保障，持久化保障

### 异步消息队列
- **短期记忆压缩**: 消息达到阈值时触发，MQ Worker 生成摘要并更新 Redis
- **长期记忆提取**: LLM 从对话中提取 profile / preference / project / relation
- **Checkpoint 持久化**: 异步写入 PostgreSQL
- **RAG 仓库/文件入库**: 异步处理 Git 仓库克隆和代码块入库

### 流式输出
- **SSE 实时推送**: 每个 token 实时输出
- **Token 统计**: 完成后返回完整 Token 消耗

## 技术栈

| 类别 | 技术 |
|------|------|
| Web 框架 | FastAPI + Uvicorn |
| Agent 框架 | LangGraph (StateGraph + create_agent) |
| LLM | OpenAI 兼容 API (默认 gpt-4o-mini，支持 DashScope Qwen 系列) |
| Embedding | OpenAI 兼容 API (默认 text-embedding-v3，1024 维) |
| 数据库 | PostgreSQL 16 + pgvector |
| 缓存 | Redis 7 |
| 消息队列 | RabbitMQ 3.x (aio-pika) |
| 序列化 | orjson / msgpack |

## 快速开始

### 环境要求

- Python 3.11+
- PostgreSQL 16+ (需安装 pgvector 扩展)
- Redis 7+
- RabbitMQ 3.x+

### 1. 克隆项目

```bash
git clone <repo-url>
cd ai-agent-engine
```

### 2. 安装依赖

```bash
# 创建 conda 环境
conda create -n rag-env python=3.11
conda activate rag-env

# 安装依赖
pip install -e .
```

### 3. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入实际配置：

```env
# LLM 配置 (OpenAI 兼容 API，支持 DashScope)
OPENAI_API_KEY=your-actual-api-key
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_EMBEDDING_MODEL=text-embedding-v3
OPENAI_EMBEDDING_DIMS=1024
AGENT_MODEL_NAME=gpt-4o-mini

# 数据库
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/ai_agent

# Redis
REDIS_URL=redis://localhost:6379/0

# RabbitMQ
RABBITMQ_URL=amqp://guest:guest@localhost:5672/
```

# 数据库
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/ai_agent

# Redis
REDIS_URL=redis://localhost:6379/0

# RabbitMQ
RABBITMQ_URL=amqp://guest:guest@localhost:5672/
```

### 4. 初始化数据库

```bash
python scripts/init_db.py
```

该脚本会创建：
- `checkpoints` / `checkpoint_blobs` / `checkpoint_writes` 表（对话状态持久化）
- `store` 表（长期记忆原始数据）
- `store_vectors` 表（长期记忆向量索引，1024 维）
- `code_chunks` / `projects` 表（RAG 代码块存储）
- `user_instructions` 表（用户指令记忆存储）
- 相关索引

### 5. 启动服务

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Docker 部署

```bash
docker-compose up -d
```

`docker-compose.yml` 包含：
- `ai-agent-engine` — 应用服务
- `postgres` — pgvector/pgvector:pg16
- `redis` — redis:7-alpine

> RabbitMQ 需单独部署或添加到 docker-compose.yml。

### 访问 API 文档

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 编排引擎详解

### 节点说明

| 节点 | 职责 | 输入 | 输出 |
|------|------|------|------|
| **Router** | 判断任务复杂度 | 用户消息 | task_complexity (simple/complex/code_audit) |
| **Simple Handler** | 处理简单任务 | 用户消息 + 记忆 | AI 回复 |
| **Analyzer** | 分析规划复杂任务 | 用户消息 + 工具列表 | ExecutionPlan (分步计划) |
| **Executor** | 执行每个步骤 | 规划步骤 + 工具 | 步骤执行结果 |
| **Judge** | 评估执行结果 | 执行结果 | JudgeResult (passed/reasons) |
| **Reporter** | 生成总结报告 | 完整执行过程 | 面向用户的总结 |
| **CodeRetriever** | 代码检索 | 审计文件列表 | RAG 上下文 |
| **VulnerabilityAnalyzer** | 漏洞分析 | 代码 + RAG 上下文 | 漏洞列表 |
| **AuditReporter** | 生成审计报告 | 漏洞列表 | 安全审计报告 |

### 路由流程

![alt text](image.png)

### 反思循环

当 Judge 评估结果为 `passed=false` 且 `iteration_count < max_iterations` 时，自动返回 Analyzer 重新规划：

- **最多迭代 3 次**
- **每次迭代**: Analyzer 可能调整执行策略
- **避免死循环**: 超过 3 次直接进入 Reporter

## 记忆系统详解

### 短期记忆（异步压缩）

**压缩策略**：

| 条件 | 行为 |
|------|------|
| 消息 < 30 条 | 全量携带，不压缩 |
| 消息 >= 30 条 | 触发 MQ 异步压缩 |
| 压缩时 | 保留最新 20 条，压缩之前的消息 |

**工作流程**：

```
对话请求
    │
    ├─► 读取 Redis 摘要 ({session_id}_summary)
    │
    ├─► 拼入 prompt: [摘要] + [历史消息] + [当前消息]
    │
    ├─► 执行节点
    │
    └─► 检查 len(messages) >= 30
            │
            ├─ 是 → 发送 MQ 消息（含序列化消息内容）
            │
            └─ 否 → 结束

MQ Worker:
    ├─► 收到消息
    ├─► 提取待压缩消息（messages[:-20]）
    ├─► 调用 LLM 生成摘要
    ├─► 新摘要 = merge(旧摘要, 新压缩内容)
    └─► 更新 Redis {session_id}_summary
```

**存储位置**：
- Redis Key: `stm_summary:{session_id}` — 对话摘要

**注入方式**：
- 拼接到 system prompt 作为上下文
- 确保多轮对话上下文连贯

### 长期记忆

- **触发**: 对话 user 消息 >= 10 条时，通过 MQ 异步提取
- **提取**: LLM 从对话中提取 profile / preference / project / relation 四类记忆
- **存储**: PostgreSQL `store` 表 (原始数据) + `store_vectors` 表 (向量索引)
- **检索**: 通过向量语义相似度搜索

### Checkpoint (对话状态)

- **两级缓存**: Redis 同步写入 (快速读取) + PostgreSQL 异步持久化 (持久保障)
- **存储内容**: 完整 `OrchestratorState`，包含 messages、execution_plan 等
- **作用**: 支持对话中断恢复，保障状态不丢失

### 用户指令记忆

用户可以通过 API 设置个性化约束指令，大模型会在每次对话中严格遵循这些约束。

**使用场景**：
- 代码风格定制（如：必须添加详细注释、使用中文注释）
- 输出格式要求（如：使用 Markdown 格式、分点说明）
- 行为约束（如：回复要简洁、避免冗余）

**存储策略**：
- **Redis (L1)**: TTL 7天，快速读写
- **PostgreSQL (L2)**: 持久化存储，Redis 过期后自动回填
- **缓存失效**: Redis 过期自动删除，DB 不受影响；更新时版本号 +1

**注入位置**：
用户指令会在以下节点的 System Prompt 中注入：
- `Simple Handler` - 简单任务处理
- `Analyzer` - 复杂任务分析规划
- `Executor` - 任务执行

**注入格式**：

```
## 用户个性化约束（严格遵守）

{用户指令内容}

---
以上是用户对该次对话的个性化约束，请严格按照上述约束生成回复。
```

### 数据流

```
用户消息 → Router (复杂度判断)
  │
  ├─► Simple Handler
  │    ├─ 加载长期记忆 (Store 向量搜索)
  │    ├─ 读取短期记忆摘要 (Redis)
  │    ├─ 提取近期消息 (state["messages"])
  │    ├─ ReAct Agent 执行
  │    └─ 检查触发压缩 (>= 30条 → MQ)
  │
  ├─► Analyzer → Executor → Judge → Reporter
  │    │         │         │        │
  │    │         │         │        ├─ 加载短期记忆摘要 + 长期记忆
  │    │         │         ├─ 加载短期记忆摘要 + 长期记忆
  │    │         └─ 加载短期记忆摘要 + 长期记忆
  │    └─ 加载短期记忆摘要 + 长期记忆
  │
  └─► CodeRetriever → VulnerabilityAnalyzer → AuditReporter
       │                    │
       └─ RAG 上下文 ────────┘

所有节点执行后:
  ├─ Checkpointer 自动持久化 (Redis + PostgreSQL)
  └─ 后处理 (MQ 异步)
       ├─ 短期记忆压缩 → Redis {session_id}_summary
       └─ 长期记忆提取 → Store (PostgreSQL + pgvector)
```

## API 接口

### 对话接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/v1/agent/chat/stream` | POST | 流式对话 (SSE) |
| `/v1/agent/chat` | POST | 非流式对话 |
| `/v1/agent/audit/stream` | POST | 代码审计流式接口 (SSE) |
| `/v1/agent/audit` | POST | 代码审计非流式接口 |

**对话请求体：**

```json
{
  "user_id": "123",
  "session_id": "123",
  "message": "帮我分析一下后端开发现状"
}
```

**审计请求体：**

```json
{
  "user_id": "123",
  "session_id": "123",
  "project_name": "my-project",
  "files": [
    {
      "file_path": "src/main.py",
      "content": "print('hello')",
      "language": "python",
      "diff": null
    }
  ],
  "audit_type": "security"
}
```

**流式响应 (SSE)：**

```
event: message
data: {"type": "content", "text": "开始分析..."}

event: message
data: {"type": "content", "text": "后端开发"}

event: message
data: {"type": "content", "text": "现状分析..."}

event: message
data: {"type": "done"}
```

**测试流式接口 (curl)：**

```powershell
curl -N -X POST http://localhost:8000/v1/agent/chat/stream -H "Content-Type: application/json" -d "{\"user_id\":\"123\",\"session_id\":\"123\",\"message\":\"你好\"}"
```

### RAG 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/v1/rag/ingest/repo` | POST | Git 仓库入库 |
| `/v1/rag/ingest/files` | POST | 文件批量入库 |
| `/v1/rag/tasks/{task_id}` | GET | 查询任务状态 |
| `/v1/rag/projects` | GET | 列出所有项目 |
| `/v1/rag/projects/{project_name}` | GET | 获取项目状态 |
| `/v1/rag/projects/{project_name}` | DELETE | 删除项目 |

**仓库入库请求体：**

```json
{
  "repo_url": "https://github.com/user/repo.git",
  "branch": "main",
  "project_name": "my-project",
  "target_extensions": [".py", ".java", ".js"]
}
```

**文件入库请求体：**

```json
{
  "project_name": "my-project",
  "files": [
    {
      "file_path": "src/main.py",
      "content": "print('hello')",
      "language": "python"
    }
  ]
}
```

### 用户指令接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/v1/user/instruction` | POST | 设置用户指令 |
| `/v1/user/instruction/{user_id}` | GET | 获取用户指令 |
| `/v1/user/instruction/{user_id}` | DELETE | 删除用户指令 |
| `/v1/user/instruction/{user_id}/exists` | GET | 检查是否存在 |

**设置用户指令请求体：**

```json
{
  "user_id": "user_123",
  "instruction_content": "代码风格要求：\n1. 必须添加详细的注释\n2. 使用中文注释\n3. 变量命名采用驼峰式"
}
```

**获取用户指令响应：**

```json
{
  "user_id": "user_123",
  "instruction_content": "代码风格要求：\n1. 必须添加详细的注释\n2. 使用中文注释\n3. 变量命名采用驼峰式",
  "version": 1,
  "updated_at": "2024-01-01T00:00:00Z"
}
```

### 其他接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/v1/health` | GET | 健康检查 |

## 项目结构

```
ai-agent-engine/
├── app/
│   ├── main.py                          # FastAPI 应用入口
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py                  # 全局配置 (Pydantic Settings)
│   │   └── mcp.yaml                     # MCP 服务器配置
│   ├── api/
│   │   ├── router.py                    # 路由注册
│   │   ├── deps.py                      # 依赖注入 (OrchestratorEngine)
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   ├── chat_request.py          # 对话请求模型
│   │   │   ├── chat_response.py         # 对话响应模型
│   │   │   ├── audit_request.py         # 审计请求模型
│   │   │   ├── rag_request.py           # RAG 请求模型
│   │   │   └── user_instruction_request.py  # 用户指令请求模型
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── agent.py                 # 对话/审计接口
│   │       ├── rag.py                  # RAG 接口
│   │       ├── user_instruction.py     # 用户指令接口
│   │       └── health.py                # 健康检查
│   ├── core/
│   │   ├── agent/
│   │   │   ├── __init__.py
│   │   │   └── engine.py                # OrchestratorEngine 工厂函数
│   │   ├── llm/
│   │   │   ├── __init__.py
│   │   │   └── service.py               # LLM 调用服务 (DashScope)
│   │   ├── memory/
│   │   │   ├── loader.py                # 长期记忆加载器
│   │   │   ├── shortmem.py              # 短期记忆压缩 (Redis)
│   │   │   ├── user_instruction.py      # 用户指令记忆服务
│   │   │   ├── checkpoint/
│   │   │   │   ├── __init__.py
│   │   │   │   └── saver.py             # Checkpoint 两级缓存 (Redis + PG)
│   │   │   ├── longterm/
│   │   │   │   ├── __init__.py
│   │   │   │   └── extractor.py         # 长期记忆提取器
│   │   │   └── mq/
│   │   │       ├── __init__.py          # MQ 路由常量
│   │   │       ├── service.py           # RabbitMQ 消息队列服务
│   │   │       └── handlers.py          # MQ 消息处理器
│   │   ├── orchestrator/                # 多级 Agent 编排模块
│   │   │   ├── __init__.py
│   │   │   ├── graph.py                # 编排图定义 (Router + 条件路由)
│   │   │   ├── state.py                # OrchestratorState 定义
│   │   │   ├── schemas.py              # ExecutionPlan / JudgeResult 等
│   │   │   ├── prompts.py              # 各节点系统提示词
│   │   │   ├── memory.py               # 编排器全局记忆组件
│   │   │   ├── simple_agent.py         # ReAct Agent 构建函数
│   │   │   ├── utils.py                # 编排器公共工具函数
│   │   │   └── nodes/
│   │   │       ├── __init__.py
│   │   │       ├── router.py           # 复杂度路由节点
│   │   │       ├── simple_handler.py   # 简单任务处理器
│   │   │       ├── analyzer.py         # 复杂任务分析规划节点
│   │   │       ├── executor.py         # 任务执行节点
│   │   │       ├── judge.py            # 执行结果评估节点
│   │   │       ├── reporter.py         # 总结报告节点
│   │   │       ├── code_retriever.py   # 代码检索节点
│   │   │       ├── vulnerability_analyzer.py  # 漏洞分析节点
│   │   │       └── audit_reporter.py  # 审计报告节点
│   │   └── rag/
│   │       ├── __init__.py
│   │       ├── engine.py               # RAG 引擎
│   │       ├── schemas.py              # RAG 数据结构
│   │       ├── chunker.py              # 代码分块器
│   │       ├── embedder.py             # Embedding 服务
│   │       ├── retriever.py            # 检索器
│   │       ├── retrieval_store.py      # 检索存储
│   │       ├── reranker.py             # 重排序
│   │       ├── query_rewriter.py       # 查询改写
│   │       └── git_loader.py           # Git 仓库加载器
│   ├── infrastructure/
│   │   ├── __init__.py
│   │   ├── redis_client.py             # Redis 客户端 (底层连接)
│   │   ├── db_client.py                # PostgreSQL 客户端 (底层连接)
│   │   ├── mq_client.py                # RabbitMQ 客户端 (底层连接)
│   │   ├── redis_service.py            # Redis 基础设施服务 (短期记忆/Checkpoint/位置存储)
│   │   ├── db_service.py               # PostgreSQL 基础设施服务 (Checkpoint持久化)
│   │   └── mq_publisher.py             # RabbitMQ 发布服务 (异步任务发布)
│   ├── tools/                          # 工具层 (MCP)
│   │   ├── __init__.py                  # 工具层导出
│   │   ├── mcp/
│   │   │   ├── __init__.py             # MCP 模块导出
│   │   │   ├── config.py               # MCP 配置加载器
│   │   │   └── manager.py              # MCP 服务管理器
│   │   └── (其他工具模块)
│   └── utils/
│       ├── __init__.py
│       ├── logger.py                   # 结构化日志 (structlog)
│       ├── trace.py                    # 链路追踪上下文
│       ├── retry.py                    # 重试工具
│       └── sse.py                      # SSE 工具
├── scripts/
│   └── init_db.py                      # 数据库初始化脚本
├── tests/                              # 测试
├── docker-compose.yml                  # Docker Compose
├── Dockerfile                          # Docker 镜像
├── pyproject.toml                      # 项目配置
└── .env.example                        # 环境变量示例
```

## 配置说明

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `ENVIRONMENT` | dev | 运行环境 |
| `SERVER_HOST` | 0.0.0.0 | 服务监听地址 |
| `SERVER_PORT` | 8000 | 服务监听端口 |
| `DATABASE_URL` | postgresql+asyncpg://... | PostgreSQL 连接 URL |
| `REDIS_URL` | redis://localhost:6379/0 | Redis 连接 URL |
| `RABBITMQ_URL` | amqp://guest:guest@localhost:5672/ | RabbitMQ 连接 URL |
| `OPENAI_API_KEY` | - | OpenAI API Key（必需） |
| `OPENAI_BASE_URL` | https://api.openai.com/v1 | OpenAI API Base URL |
| `OPENAI_EMBEDDING_MODEL` | text-embedding-v3 | Embedding 模型名称 |
| `OPENAI_EMBEDDING_DIMS` | 1024 | Embedding 向量维度 |
| `AGENT_MODEL_NAME` | gpt-4o-mini | Agent LLM 模型名称 |
| `LOG_LEVEL` | INFO | 日志级别 |
| `LOG_FORMAT` | json | 日志格式 (json/console) |

## MCP 服务配置

MCP (Model Context Protocol) 服务支持通过 YAML 配置文件集中管理多个 MCP 服务器。

### 配置文件位置

```
app/config/mcp.yaml
```

### 配置示例

```yaml
mcp:
  # 飞书 MCP
  lark:
    enabled: true  # 设置为 true 启用
    command: npx
    args:
      - "-y"
      - "@larksuiteoapi/lark-mcp"
      - "mcp"
      - "-a"
      - "YOUR_FEISHU_APP_ID"    # 硬编码 App ID
      - "-s"
      - "YOUR_FEISHU_APP_SECRET"  # 硬编码 App Secret
    transport: stdio
    env:
      NODE_NO_WARNINGS: "1"
    tags:
      - lark
      - feishu

  # GitHub MCP
  github:
    enabled: false
    command: npx
    args:
      - "-y"
      - "@modelcontextprotocol/server-github"
    transport: stdio
    tags:
      - github
```

### 配置字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `enabled` | bool | 是 | 是否启用该 MCP 服务器 |
| `command` | string | 是 | 启动命令 (如 npx, python, node) |
| `args` | list | 是 | 命令参数列表 |
| `transport` | string | 是 | 传输类型: stdio / http / sse / streamable_http |
| `url` | string | 否 | HTTP 传输时的 URL |
| `headers` | dict | 否 | HTTP 请求头 |
| `env` | dict | 否 | 子进程环境变量 |
| `tags` | list | 是 | 工具标签，用于分组获取工具 |

### 使用工具

```python
from app.tools.mcp import get_mcp_manager

# 获取所有 MCP 工具
mcp_manager = get_mcp_manager()
all_tools = await mcp_manager.get_tools()

# 获取特定标签的工具
lark_tools = await mcp_manager.get_tools(tags=["lark"])

# 获取多个标签的工具
selected_tools = await mcp_manager.get_tools(tags=["lark", "github"])
```

## 架构原则

### 分层设计

本项目采用清晰的分层架构，确保各层职责明确、耦合度低：

```
┌─────────────────────────────────────────────────────────────┐
│                      业务层 (Business)                        │
│  shortmem.py / checkpoint/saver.py / handlers.py            │
│  ✅ 调用基础设施服务，不直接操作底层客户端                      │
└─────────────────────────────┬───────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────┐
│                  基础设施服务层 (Infrastructure Service)      │
│  redis_service.py / db_service.py / mq_publisher.py         │
│  ✅ 封装所有 Redis/DB/MQ 操作，提供高级业务方法               │
└─────────────────────────────┬───────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────┐
│                    客户端层 (Clients)                         │
│  redis_client.py / db_client.py / mq_client.py              │
│  ✅ 仅负责连接管理和基础操作，被服务层内部调用                 │
└─────────────────────────────────────────────────────────────┘
```

### 服务职责

| 服务层 | 职责 |
|--------|------|
| **RedisService** | 短期记忆（摘要/计数器）、长期记忆位置、Checkpoint读写、RAG任务状态 |
| **DbService** | Checkpoint 持久化、查询 |
| **MQPublisher** | 短期记忆压缩任务、长期记忆提取任务、Checkpoint持久化任务、RAG入库任务 |

### 重构收益

| 方面 | 收益 |
|------|------|
| **耦合度** | 业务层直接依赖抽象服务接口，而非具体实现 |
| **可测试性** | 易于注入 mock 服务进行单元测试 |
| **可替换性** | 更换 Redis/DB 只需修改 service 实现 |
| **可维护性** | 基础设施逻辑集中管理 |
| **可读性** | 业务代码清晰专注业务逻辑 |

## 消息队列任务类型

| 队列 | 路由 Key | 功能 |
|------|---------|------|
| `q.shortmem.compress` | `shortmem.compress` | 短期记忆压缩 |
| `q.longterm.extract` | `longterm.extract` | 长期记忆提取 |
| `q.checkpoint.persist` | `checkpoint.persist` | Checkpoint 持久化 |
| `q.checkpoint.writes` | `checkpoint.writes` | Checkpoint Writes 持久化 |
| `q.rag.ingest.repo` | `rag.ingest.repo` | Git 仓库入库 |
| `q.rag.ingest.files` | `rag.ingest.files` | 文件批量入库 |

## 开发指南

### 运行测试

```bash
pytest tests/ -v --cov=app
```

### 代码格式化

```bash
black app/ tests/
ruff check app/ tests/
```

### 类型检查

```bash
mypy app/
```

## License

Apache License 2.0
