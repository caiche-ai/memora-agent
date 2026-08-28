# Memora 智能助理

Memora 是一个前后端分离的 AI 工作助理：后端提供聊天、项目、知识文件、会议分析、长期记忆、联网搜索、邮件和 PPT API，前端提供统一的浏览器操作界面。

## 项目结构

```text
backend/
  memora/                 FastAPI 应用
    app.py                API 路由与能力编排
    main.py               后端启动入口
    store.py              SQLite 数据层
    services/             文件、会议、模型、搜索、邮件、记忆、PPT
      intent.py           统一消息意图路由
      context.py          对话历史、@文件、项目知识、记忆和联网上下文构建
      workflow.py         聊天与 Artifact 工作流执行
      provider.py         外部服务超时、重试、熔断和健康状态
      tasks.py            SQLite 持久化任务执行器
      observability.py    Trace 上下文与阶段事件
  tests/                  后端自动化测试
  examples/               示例会议原文
  data/                   SQLite、日志和生成文件（不提交 Git）
  .env                    后端私密配置（不提交 Git）
  pyproject.toml           Python 依赖

frontend/
  src/app.js              页面逻辑和 API 调用
  src/styles.css          页面样式
  index.html              页面入口
  vite.config.js          开发服务器和 API 代理
  package.json            前端依赖
```

## 本地启动

需要分别启动后端和前端。

### 1. 启动后端

打开第一个 PowerShell：

```powershell
cd backend
uv sync
uv run python -m memora.main
```

后端地址：<http://127.0.0.1:8000>
API 文档：<http://127.0.0.1:8000/api/docs>

### 2. 启动前端

打开第二个 PowerShell：

```powershell
cd frontend
npm install
npm run dev
```

前端地址：<http://127.0.0.1:5173>

开发环境中，Vite 会把前端的 `/api` 请求代理到 `http://127.0.0.1:8000`。

## 后端配置

真实配置位于 `backend/.env`，示例见 `backend/.env.example`：

```dotenv
BACKEND_HOST=127.0.0.1
PORT=8000
FRONTEND_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

# 阿里云百炼千问
LLM_API_KEY=your-key
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus

# Provider 可靠性策略
PROVIDER_MAX_ATTEMPTS=3
PROVIDER_BACKOFF_SECONDS=0.5
PROVIDER_CIRCUIT_THRESHOLD=5
PROVIDER_CIRCUIT_SECONDS=30

# 混合检索 Embedding（Key 留空时复用 LLM_API_KEY）
EMBEDDING_API_KEY=
EMBEDDING_MODEL=text-embedding-v4

# 可选扫描 PDF OCR 服务
OCR_API_URL=
OCR_API_KEY=

# 可选：Tavily 搜索
TAVILY_API_KEY=

# 推荐：AgentMail 系统邮箱（INBOX_ID 可留空，首次发送自动创建）
AGENTMAIL_API_KEY=your-agentmail-key
AGENTMAIL_INBOX_ID=
AGENTMAIL_BASE_URL=https://api.agentmail.to/v0

# 可选备用：个人 SMTP 邮件
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_SECURE=false
SMTP_USER=your-user
SMTP_PASS=your-password
SMTP_FROM=assistant@example.com

# 生产环境建议设置，用于加密前端保存的邮件授权码
SETTINGS_ENCRYPTION_KEY=
```

不配置模型时，知识文件本地检索、会议规则分析、长期记忆、待办管理和 PPT 文件生成仍可运行。配置 `AGENTMAIL_API_KEY` 后，系统会优先使用 AgentMail，普通用户无需填写邮箱授权码；如同时配置个人 SMTP，可在发送窗口切换。邮件不会自动发送，仍必须由用户在前端确认。

升级前已经上传的文件会自动重建 FTS5 索引。配置 Embedding 后，可调用 `POST /api/index/rebuild` 为旧文件补齐语义向量；新上传或编辑的文件会自动建立索引。

### AgentMail 使用方式

1. 在 AgentMail 控制台创建 API Key，填入 `backend/.env` 的 `AGENTMAIL_API_KEY`。
2. `AGENTMAIL_INBOX_ID` 可以留空；首次发送时后端会自动创建一个 Memora 系统邮箱，并将邮箱地址保存在数据库设置中供后续复用。
3. 重启后端。前端左下角“邮件设置”会显示“AgentMail 系统邮箱 · 已启用”。
4. 在项目待办中点击“发邮件”，确认收件人和内容后发送；若同时配置了个人 SMTP，可在发送窗口切换发件方式。

AgentMail API Key 只保存在后端，不会返回给浏览器。系统邮箱用于应用统一发信，个人 SMTP 仅作为用户主动选择的备用通道。

## 前端配置

`frontend/.env.example` 包含两个可选变量：

```dotenv
# 开发代理目标
VITE_PROXY_TARGET=http://127.0.0.1:8000

# 前端和后端分别部署时设置，例如 https://api.example.com
VITE_API_BASE_URL=
```

本地开发无需创建前端 `.env`。独立部署时，在构建前配置 `VITE_API_BASE_URL`：

```powershell
cd frontend
$env:VITE_API_BASE_URL='https://api.example.com'
npm run build
```

构建产物位于 `frontend/dist/`，由 Nginx、对象存储或其他静态服务器部署；FastAPI 不再托管前端文件。

## 功能说明

- 项目空间：采用 ChatGPT Projects 风格主页，在大输入框下集中展示项目资料和最近聊天；左侧项目展开后显示项目内对话。顶部只保留会议和资料库，待办在会议中跟进，项目记忆在右上角三点菜单中管理。已有会议会自动归入“默认项目”。
- 项目聊天：每个项目可新建多个独立对话，自动检索该项目资料库及项目记忆；项目对话不会混入左侧普通聊天历史。
- 项目资料库：支持上传、展示和移除 PDF、TXT、Markdown；使用 SQLite FTS5 与可选千问 Embedding 混合召回，并按标题、词面和语义相关度重排。
- 新聊天：保持独立的聊天历史、知识文件问答、联网搜索和 PPT 生成流程。
- 对话知识文件：支持 PDF、TXT、Markdown，绑定到上传时的新聊天，用于基于原文的问答和页码引用；与项目背景知识相互隔离。
- 会议 TXT：在选定项目中上传，随后提取摘要、人物、时间、地点、风险、决策和待办。
- 长期记忆：自动沉淀聊天和会议中的人物、主题、时间、地点、偏好、事实、决策与风险；普通聊天与每个项目严格隔离。记忆包含置信度、有效期、敏感级别和版本关系，相同主题的新事实可替代旧事实，过期记忆不会注入回答。
- 联网搜索：时效性问题自动调用 Tavily 或 DuckDuckGo。
- PPT：在对话中明确要求后，复用统一上下文读取 `@文件`、当前项目资料、长期记忆和需要的联网结果，再生成可编辑的 `.pptx` 文件；Artifact 会记录所用来源便于追踪。
- 邮件：默认支持 AgentMail 系统邮箱，也可在前端配置并测试个人 SMTP 备用邮箱；待办邮件仍需确认后发送。

PDF 默认直接提取文本；配置 `OCR_API_URL` 后，无法提取文本的扫描 PDF 会自动提交 OCR 服务。OCR 服务需接收名为 `file` 的 PDF，并返回 `{pages:[{page_number,text}]}`。

## 消息工作流

聊天消息统一按“意图路由 → 混合检索 → 上下文预算与对话摘要 → 工作流执行 → 来源记录”处理。前端通过持久化消息任务提交并轮询结果；后端进程重启后会恢复未完成任务。`@文件`严格限定资料范围；未指定文件时使用 FTS5、Embedding 和重排从当前作用域召回。长期记忆提取也使用持久化后台任务，不会把当前消息刚提取的记忆重复注入同一次回答。

### 任务、幂等与 Trace

- `POST /api/conversations/{id}/message-tasks` 创建消息任务，`GET /api/tasks/{taskId}` 查询状态和结果；失败任务可通过 `POST /api/tasks/{taskId}/retry` 重试，排队任务可取消。
- 前端为消息和邮件生成幂等键。同一个消息请求只执行一次；同一封邮件即使重复点击或请求重放，也不会重复投递。同步消息接口 `/api/conversations/{id}/messages` 继续保留用于兼容。
- `GET /api/traces` 和 `GET /api/traces/{traceId}` 可查看路由、上下文构建、工作流、Provider 调用、持久化及任务重试事件。
- `GET /api/health` 的 `providers` 字段展示当前进程内各外部服务的失败次数和熔断状态。Provider 的重试仅针对连接失败、限流和 5xx 等临时错误。
- 左侧“任务中心”展示等待、执行、完成、失败和死信任务，提供阶段进度、Trace 时间线、取消与重新执行操作；打开窗口时每 2 秒刷新一次。
- 可重试错误耗尽自动重试后进入 `dead_letter`。消息任务会自动补偿同一执行写入的半截消息、Artifact 数据和 `data/artifacts` 安全目录内的生成文件；参数校验等不可重试错误不会进入死信。
- `GET /api/dead-letters` 查询死信，`POST /api/dead-letters/{taskId}/compensate` 可再次执行补偿，`POST /api/dead-letters/{taskId}/resolve` 用于人工关闭。
- 失败邮件会出现在任务中心的“邮件投递异常”中。由于网络超时后无法可靠判断邮箱服务是否已经接收，系统不会自动重复投递；用户应先核对发件箱，再决定是否从原 Artifact/待办重发，并通过 `POST /api/email-deliveries/{deliveryId}/resolve` 标记已处理。

## 验证

后端：

```powershell
cd backend
uv run pytest
uv run ruff check memora tests
uv run ruff format --check memora tests
```

前端：

```powershell
cd frontend
npm run build
```

## 数据与安全

- `.env`、SQLite 数据库、日志和生成文件均已忽略，不会提交 Git。
- 前端保存的 SMTP 配置使用 Fernet 加密。开发环境会自动生成 `backend/data/.settings.key`；生产环境应通过 `SETTINGS_ENCRYPTION_KEY` 提供独立主密钥并妥善备份。
- 后端只允许下载 `backend/data/artifacts` 中登记的文件。
- 上传限制：知识文件 25 MB、会议 TXT 8 MB、消息 20,000 字。
- 当前是单用户 MVP，对外部署前应增加认证、权限、限流、审计和敏感信息脱敏。
