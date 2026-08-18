# 本地 AI 工作台（Local AI Workbench）

一个**部署在客户本地、保护隐私**的 Web 应用骨架：
知识库问答 + AI 对话，全部运行在本机，数据不出门。

## 功能

- 💬 **AI 对话**：网页聊天界面，像本地版 ChatGPT
- 📚 **知识库问答（RAG）**：上传文档 → 句子级切片 → 语义检索 → 自动引用回答
- 🧰 **工具中心**：批量文本处理（翻译/改写/生成）、批量作图、表格批量处理
- 📊 **运行监控**：每次调用的日志明细、token 消耗统计、估算成本、冗余/无效运行检测
- 🖥 **纯本地运行**：浏览器打开即用，数据保存在 `data/` 目录
- 🔌 **模型可插拔**：对话模型（DeepSeek/Ollama/mock）+ 向量模型（fastembed/Ollama/API/词法）+ 生图（API/占位图）

## 工具中心说明

| 工具 | 用法 | 说明 |
|---|---|---|
| ① 批量文本 | 每行一条文本 → 选"改写/翻译/生成" → 运行 → 复制/下载 | 用对话模型处理，token 自动计入监控 |
| ② 批量作图 | 每行一个提示词 → 选尺寸 → 生成 → 下载 | 默认"占位图"模式测流程；接生图 API 后自动切换真实生图 |
| ③ 表格处理 | 上传 Excel/CSV → 解析 → 选列 → 处理 → 下载结果 | 结果追加"处理结果"列；支持 xlsx/csv、UTF-8/GBK |

### 接真实生图 API（②批量作图）

注册生图服务（如硅基流动 https://siliconflow.cn），在 `.env` 配置：

```ini
IMAGE_PROVIDER=api
IMAGE_API_BASE_URL=https://api.siliconflow.cn/v1
IMAGE_API_KEY=sk-你的生图密钥
IMAGE_API_MODEL=black-forest-labs/FLUX.1-schnell
```

## 运行监控说明

界面顶部「📊 运行监控」页可以看到：

| 能力 | 说明 |
|---|---|
| 统计卡片 | 对话次数、输入/输出 tokens、**估算成本**、错误次数、平均耗时 |
| 冗余检测 | 自动识别"同一问题重复提问"并估算浪费的 tokens；识别知识库 0 命中检索 |
| 日志明细 | 每条调用记录：时间、类型（对话/检索/上传/删除）、状态、耗时、token 数、详情 |
| 成本估算 | 按 `PRICE_IN_PER_M` / `PRICE_OUT_PER_M`（默认 DeepSeek 参考价）估算，可在 `.env` 修改 |

日志保存在 `data/logs.jsonl`，重启服务不丢失；界面可一键清空。

## 知识库检索（RAG）说明

### 切片（v2：句子级）
- 按**句末标点**切分，**不会把句子从中间切断**；
- 自动识别并记录**章节标题**（Markdown 标题/短行），引用时精确到章节；
- 块长设下限 `CHUNK_MIN_SIZE`（默认 80 字），避免碎片化。

### 检索（语义 + 词法双模）
- **语义模式（默认）**：本地 fastembed 模型 `BAAI/bge-small-zh-v1.5`（90MB，免费、离线、数据不出门）——能理解"我的钱什么时候能回来"≈"退款"这类**同义表达**；
- **词法模式（回退）**：fastembed 不可用时自动降级为关键词检索，系统永不挂；
- 自动选择顺序：`EMBED_PROVIDER=auto` 时 优先 Ollama → 兼容 API → 本地 fastembed → 词法。

### 阈值与去重（消除冗余）
- `RETRIEVE_THRESHOLD`（默认 0.38）：语义相似度下限，低于此值视为未命中（过滤噪声、避免无关内容喂给模型）；
- `DEDUP_THRESHOLD`（默认 0.60）：召回去重，内容重叠过高的块只保留一个（避免重复上下文浪费 token）；
- 监控页会显示"召回去重拦截 N 条"与"0 命中检索 N 次"。

### 向量存储
- 所有向量保存在 `data/index.json`，纯本地；
- 嵌入器类型变化（词法→语义）时**自动全量重算向量**，无需手动重建。

### 可换 Embedding 方案
| 方案 | 配置 | 特点 |
|---|---|---|
| 本地 fastembed（默认） | `EMBED_PROVIDER=local` | 免费、离线、90MB |
| Ollama | `EMBED_PROVIDER=ollama` + 安装 Ollama `ollama pull nomic-embed-text` | 免费、离线、可换大模型 |
| OpenAI 兼容 API | `EMBED_PROVIDER=api` + 填 `EMBED_API_BASE_URL/KEY/MODEL` | 效果最好，按量付费 |

## 快速开始（Windows）

双击 **`start.bat`**，或手动：

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python run.py
```

浏览器打开 **http://127.0.0.1:8000** 即可使用。

> 默认是「演示模式」，不需要任何模型和 API key，先跑通界面和知识库流程。
> 右侧上传 .txt/.md/.csv/.json/.log 文件即可建立知识库，然后提问。

## 切换真实模型

复制 `.env.example` 为 `.env` 并修改：

**方式一：Ollama 本地模型（免费、离线、推荐给客户）**
```ini
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen2.5:3b
```
需要先安装 Ollama（https://ollama.com）并拉取模型：`ollama pull qwen2.5:3b`
> 提示：客户电脑内存 ≥ 8GB 可跑 3B 模型；≥ 16GB 可跑 7B（qwen2.5:7b）。

**方式二：DeepSeek API（效果最好，按量付费，很便宜）**
```ini
LLM_PROVIDER=openai
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_API_KEY=sk-你的密钥
OPENAI_MODEL=deepseek-chat
```

## API 一览

| 接口 | 说明 |
|---|---|
| `GET /` | Web 界面 |
| `GET /api/health` | 健康检查 |
| `POST /api/chat` | 对话 `{message, use_kb}` |
| `POST /api/documents` | 上传文档（multipart，字段名 `file`） |
| `GET /api/documents` | 文档列表 |
| `DELETE /api/documents/{id}` | 删除文档 |
| `GET /api/logs` | 运行日志 `?limit=&type=` |
| `GET /api/stats` | 运行统计（token/成本/冗余检测） |
| `POST /api/logs/clear` | 清空日志 |

## 项目结构

```
local-ai-app/
├── app/
│   ├── main.py        # Flask 接口
│   ├── config.py      # 配置（.env + 环境变量）
│   ├── llm.py         # 模型接入层（mock/ollama/openai）
│   ├── rag.py         # 知识库：切片 + 检索
│   └── static/
│       └── index.html # Web 界面
├── data/              # 运行时数据（自动创建）
├── run.py             # 启动入口
└── start.bat          # Windows 一键启动
```

## 给客户的交付话术（怎么卖）

> "这套系统装在你们自己电脑/内网服务器上，**文档、数据全部留在本地，绝不上云**。
> 员工打开浏览器就能问它问题——产品资料、合同条款、操作手册都能查。
> 一次部署 + 首月维护，之后按年维护。"
