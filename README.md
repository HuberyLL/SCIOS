# SCIOS - Smart Research Agent

SCIOS 是一款本地运行的学术智能助手，专注于自动化主题探索与持续学术动态监控。

## 🚀 快速启动指南

### 1. 启动后端 (Backend)

后端提供了核心的 Agent 流水线与 API 接口。

```bash
# 进入后端目录
cd backend

# 复制并配置环境变量 (请在 .env 中填入你的 API Keys: OpenAI/Gemini/Tavily/Semantic Scholar)
cp .env.example .env

# 同步依赖 (推荐使用 uv)
uv sync

# 启动 FastAPI 开发服务器
uv run fastapi dev src/main.py
# 或者使用 uvicorn: uv run uvicorn src.main:app --reload --port 8000
```
后端启动后，接口地址默认在：`http://localhost:8000`
API 文档 (Swagger UI)：`http://localhost:8000/docs`

### 2. 启动前端 (Frontend)

前端提供了美观的用户交互界面，支持 SSE 流式状态渲染。

```bash
# 打开一个新的终端窗口，进入前端目录
cd frontend

# 安装依赖包
npm install

# 启动 Next.js 开发服务器
npm run dev
```
前端启动后，访问地址：`http://localhost:3000`

---

## 🛠️ 如何体验核心功能

1. **主题探索 (Deep Research)**
   - 打开浏览器访问 `http://localhost:3000`。
   - 在 Explore 页面的大搜索框中输入你感兴趣的学术话题，例如："Transformer in healthcare" 或 "RLHF in large language models"。
   - 点击回车，你将看到实时的 Agent 检索进度（SSE 流式推送），最终生成包含核心概念、推荐学者、经典论文及趋势分析的结构化精美报告。

2. **长期监控 (Topic Monitoring)**
   - 点击页面顶部的 "Monitor" 标签。
   - 添加一个你想持续追踪的关键词或领域。
   - 后端的定时任务会自动每天/每周在后台抓取最新论文，并生成简报。你可以在面板中点击查看历史的 Daily Brief。
   - (如果在后端 `.env` 中配置了 SMTP 邮箱，还会自动推送到你的邮箱！)
