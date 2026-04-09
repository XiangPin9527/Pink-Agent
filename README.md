# AI Agent Engine

基于 LangGraph ReAct Agent 的智能对话引擎，集成多级记忆系统和异步消息队列，为业务系统提供 AI 对话能力。

## 系统架构

```
┌──────────────────────────────────────────────────────────────────┐
│                       业务系统 (Java / 其他)                       │
│                   业务逻辑 / 认证 / 限流 / 持久化                   │
└─────────────────────────────┬────────────────────────────────────┘
                              │ HTTP (SSE / JSON)
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                  Python AI 对话引擎 (FastAPI)                     │
│                                                                   │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────────┐ │
│  │  ReAct Agent │  │  记忆系统     │  │  异步消息队列 (RabbitMQ) │ │
│  │  (LangGraph) │  │  短期+长期    │  │  摘要 / 长期记忆提取     │ │
│  └─────────────┘  └──────────────┘  └─────────────────────────┘ │
└──────────┬──────────────┬──────────────────┬─────────────────────┘
           │              │                  │
           ▼              ▼                  ▼
    ┌────────────┐  ┌──────────┐      ┌───────────┐
    │  DashScope  │  │  Redis   │      │ PostgreSQL │
    │  (LLM/Emb) │  │  (缓存)  │      │ (pgvector) │
    └────────────┘  └──────────┘      └───────────┘
```

## 核心特性

- **ReAct Agent**: 基于 LangGraph `create_agent` 构建，支持推理-行动循环，可扩展工具调用
- **SummarizationMiddleware**: 自动消息摘要与裁剪，替代传统短期记忆窗口管理，避免消息累积
- **多级记忆系统**: 长期记忆 (PostgreSQL + pgvector) + 自动摘要 (LLM 生成)
- **异步消息队列**: 基于 RabbitMQ 的可靠消息处理，驱动长期记忆提取
- **两级 Checkpoint**: Redis 同步写入 + PostgreSQL 异步持久化，保障对话状态不丢失
- **逐字流式输出**: SSE 实时推送每个 token + 完成后返回 Token 统计
- **向量语义搜索**: 长期记忆通过 pgvector 实现语义相似度检索

## 技术栈

| 类别 | 技术 |
|------|------|
| Web 框架 | FastAPI + Uvicorn |
| Agent 框架 | LangGraph (`create_agent`) |
| LLM | 阿里云 DashScope (Qwen 系列) |
| Embedding | DashScope `text-embedding-v3` (1024 维) |
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
# LLM 配置 (DashScope)
OPENAI_API_KEY=sk-your-api-key
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_EMBEDDING_MODEL=text-embedding-v3
OPENAI_EMBEDDING_DIMS=1024
AGENT_MODEL_NAME=qwen3-max

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

## API 接口

### 对话接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/v1/agent/chat/stream` | POST | 流式对话 (SSE) |
| `/v1/agent/chat` | POST | 非流式对话 |

**请求体：**

```json
{
  "user_id": "123",
  "session_id": "123",
  "message": "你好"
}
```

**流式响应 (SSE)：**

```
event: message
data: {"type": "step_start", "step": 0, "name": "agent", "text": "开始执行 Agent 任务..."}

event: message
data: {"type": "content", "text": "西"}

event: message
data: {"type": "content", "text": "安"}

event: message
data: {"type": "content", "text": "电子"}

event: message
data: {"type": "content", "text": "科技大学..."}

event: message
data: {"type": "done", "summary": "Agent 执行完成", "total_tokens": 228, "prompt_tokens": 219, "completion_tokens": 9}
```

> 流式响应逐字输出，`done` 事件中包含本轮 Token 消耗统计：
> - `total_tokens`: 本轮对话总 Token 数
> - `prompt_tokens`: 提示词 Token 数
> - `completion_tokens`: 补全 Token 数

**测试流式接口 (curl)：**

```powershell
curl -N -X POST http://localhost:8000/v1/agent/chat/stream -H "Content-Type: application/json" -d "{\"user_id\":\"123\",\"session_id\":\"123\",\"message\":\"你好\"}"
```

### 其他接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/v1/health` | GET | 健康检查 |
| `/v1/rag/ingest` | POST | 文档嵌入 |

## 记忆系统详解

### 消息摘要与裁剪 (SummarizationMiddleware)

- **实现**: LangChain `SummarizationMiddleware`，集成到 `create_agent` 构建流程
- **触发**: 当消息列表达到 40 条时，自动触发摘要生成
- **保留**: 摘要后保留最近 20 条消息
- **效果**: 替代传统短期记忆窗口管理，LLM 自动精炼历史上下文，避免 token 无限膨胀
- **注意**: 短期记忆不再通过 Redis 手动注入，而是由 Checkpointer + Middleware 自动管理

### 长期记忆

- **触发**: 对话 user 消息 >= 10 条时，通过 MQ 异步提取
- **提取**: LLM 从对话中提取 profile / preference / project / relation 四类记忆
- **存储**: PostgreSQL `store` 表 (原始数据) + `store_vectors` 表 (向量索引)
- **检索**: 通过 `store.asearch()` 进行向量语义相似度搜索

### Checkpoint (对话状态)

- **两级缓存**: Redis 同步写入 (快速读取) + PostgreSQL 异步持久化 (持久保障)
- **作用**: 支持对话中断恢复，保障状态不丢失

### 数据流

```
用户消息 → AgentEngine
  ├─ 加载长期记忆 (Store 向量搜索)
  ├─ 构建 Input Messages (SystemMessage + HumanMessage)
  ├─ ReAct Agent 执行 (流式输出 token by token)
  ├─ Checkpointer 自动持久化 (Redis + PostgreSQL)
  ├─ SummarizationMiddleware 自动摘要裁剪
  └─ 后处理 (MQ 异步)
       └─ 提取长期记忆 → Store (PostgreSQL + pgvector)
```

## 项目结构

```
ai-agent-engine/
├── app/
│   ├── main.py                          # FastAPI 应用入口
│   ├── config/
│   │   └── settings.py                  # 全局配置 (Pydantic Settings)
│   ├── api/
│   │   ├── router.py                    # 路由注册
│   │   ├── deps.py                      # 依赖注入
│   │   ├── v1/
│   │   │   ├── agent.py                 # 对话接口 (流式/非流式)
│   │   │   ├── rag.py                   # RAG 接口
│   │   │   └── health.py                # 健康检查
│   │   └── schemas/
│   │       ├── chat_request.py          # 请求模型
│   │       └── chat_response.py         # 响应模型
│   ├── core/
│   │   ├── agent/
│   │   │   ├── engine.py                # Agent 执行引擎 (核心)
│   │   │   ├── graph/
│   │   │   │   ├── __init__.py          # build_react_agent 构建
│   │   │   │   └── state.py             # AgentState 定义
│   │   │   └── prompts/
│   │   │       └── agent_prompt.py      # ReAct Agent 系统提示词
│   │   ├── llm/
│   │   │   └── service.py               # LLM 调用服务
│   │   ├── memory/
│   │   │   ├── loader.py                # 记忆加载与组装
│   │   │   ├── checkpoint/
│   │   │   │   └── saver.py             # Checkpoint 两级缓存
│   │   │   ├── summary/
│   │   │   │   └── service.py           # 会话摘要服务
│   │   │   ├── longterm/
│   │   │   │   └── extractor.py         # 长期记忆提取器
│   │   │   └── mq/
│   │   │       ├── service.py           # RabbitMQ 消息队列服务
│   │   │       └── handlers.py          # MQ 消息处理器
│   │   └── rag/
│   │       └── engine.py                # RAG 引擎
│   ├── infrastructure/
│   │   ├── redis_client.py              # Redis 客户端
│   │   ├── db_client.py                 # PostgreSQL 客户端
│   │   └── mq_client.py                 # RabbitMQ 客户端
│   ├── models/                          # 模型层
│   ├── tools/                           # 工具层 (MCP)
│   └── utils/
│       ├── logger.py                    # 结构化日志 (structlog)
│       ├── trace.py                     # 链路追踪上下文
│       ├── retry.py                     # 重试工具
│       └── sse.py                       # SSE 工具
├── scripts/
│   └── init_db.py                       # 数据库初始化脚本
├── tests/                               # 测试
├── docker-compose.yml                   # Docker Compose
├── Dockerfile                           # Docker 镜像
├── pyproject.toml                       # 项目配置
└── .env.example                         # 环境变量示例
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
| `OPENAI_API_KEY` | - | DashScope API Key |
| `OPENAI_BASE_URL` | https://api.openai.com/v1 | DashScope 兼容模式 URL |
| `OPENAI_EMBEDDING_MODEL` | text-embedding-v3 | Embedding 模型名称 |
| `OPENAI_EMBEDDING_DIMS` | 1024 | Embedding 向量维度 |
| `AGENT_MODEL_NAME` | qwen3-max | Agent LLM 模型名称 |
| `LOG_LEVEL` | INFO | 日志级别 |
| `LOG_FORMAT` | json | 日志格式 (json/console) |

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
