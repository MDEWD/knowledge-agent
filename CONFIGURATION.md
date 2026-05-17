# 知识库 Agent — 配置文档

## 目录

1. [项目结构](#项目结构)
2. [快速开始](#快速开始)
3. [后端配置](#后端配置)
4. [前端配置](#前端配置)
5. [Obsidian 集成](#obsidian-集成)
6. [模型选择](#模型选择)
7. [常见问题](#常见问题)

---

## 项目结构

```
agent/
├── backend/
│   ├── .env.example          ← 复制为 .env 并填写
│   ├── app.py                ← FastAPI 主程序
│   ├── config.py             ← 从环境变量读取配置
│   ├── requirements.txt
│   ├── extractors/           ← 字幕提取（YouTube / Bilibili / 通用 / Whisper）
│   ├── processors/           ← Claude 提炼核心观点
│   └── storage/              ← Obsidian 写入 + ChromaDB + 视频元数据
├── frontend/
│   ├── package.json
│   ├── vite.config.ts        ← 开发代理到 localhost:8000
│   └── src/
│       ├── App.tsx
│       ├── api/client.ts     ← 所有 HTTP / SSE 调用
│       ├── components/       ← VideoInput / VideoLibrary / ChatInterface
│       └── types/index.ts
└── CONFIGURATION.md          ← 本文件
```

---

## 快速开始

### 1. 配置后端环境变量

```bash
cd backend
cp .env.example .env
```

用任意编辑器打开 `.env`，**至少填写两项**：

```env
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
OBSIDIAN_VAULT=/Users/yourname/Documents/MyVault/Videos
```

### 2. 安装后端依赖

> 推荐使用 Python 3.11+，建议先创建虚拟环境。

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

> **首次运行** `sentence-transformers` 和 `whisper` 会自动下载模型文件（约 300MB），需要网络连接。

### 3. 启动后端

```bash
cd backend
python app.py
# 或：uvicorn app:app --reload --port 8000
```

后端默认运行在 `http://localhost:8000`。

### 4. 安装并启动前端

```bash
cd frontend
npm install
npm run dev
```

前端默认运行在 `http://localhost:5173`，自动代理 `/api/*` 到后端。

---

## 后端配置

所有配置均通过 `backend/.env` 文件的环境变量控制。

### 必填项

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `ANTHROPIC_API_KEY` | Anthropic API 密钥，从 [console.anthropic.com](https://console.anthropic.com) 获取 | `sk-ant-api03-...` |
| `OBSIDIAN_VAULT` | Obsidian Vault 中存放视频笔记的**绝对路径**，不存在会自动创建 | `/Users/me/MyVault/Videos` |

### 可选项

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | 用于提炼观点和聊天的 Claude 模型，见[模型选择](#模型选择) |
| `WHISPER_MODEL` | `base` | Whisper 语音识别模型，无字幕视频时使用，见下表 |
| `EMBED_MODEL` | `paraphrase-multilingual-MiniLM-L12-v2` | 向量嵌入模型，影响语义搜索质量 |
| `CHROMA_DB_PATH` | `./data/chroma_db` | ChromaDB 持久化存储路径 |
| `DATA_PATH` | `./data` | 视频元数据 JSON 文件存放路径 |
| `MAX_TRANSCRIPT_CHARS` | `80000` | 字幕最大处理字符数，超出部分截断 |

### Whisper 模型对比

仅在视频**没有字幕**时才调用 Whisper（如自制视频、直播回放）。

| 模型 | 磁盘占用 | 速度 | 准确度 | 推荐场景 |
|------|----------|------|--------|----------|
| `tiny` | ~39MB | 最快 | 较低 | 快速测试 |
| `base` | ~74MB | 快 | 一般 | **默认，日常使用** |
| `small` | ~244MB | 中 | 好 | 中文内容较多时 |
| `medium` | ~769MB | 慢 | 很好 | 专业内容、口音重 |
| `large` | ~1.5GB | 最慢 | 最好 | 高质量要求 |

---

## 前端配置

前端无需额外配置文件。如需修改 API 地址（例如后端部署在远程服务器），编辑 `frontend/vite.config.ts`：

```typescript
// 将 target 改为实际后端地址
proxy: {
  '/api': {
    target: 'http://your-server-ip:8000',
    changeOrigin: true,
  },
},
```

生产构建后，配置 Nginx 等反向代理将 `/api` 指向后端即可。

---

## Obsidian 集成

### 自动生成的笔记格式

每个视频处理完成后，会在 `OBSIDIAN_VAULT` 目录下生成一个 Markdown 文件：

```
2026-05-17 视频标题.md
```

文件包含 YAML frontmatter（可用 Dataview 插件查询）：

```yaml
---
title: "视频标题"
source: "https://youtube.com/watch?v=..."
channel: "频道名"
platform: "youtube"
date: 2026-05-17
type: video-note
---
```

正文结构：
- `## 核心摘要`
- `## 主要观点`
- `## 关键概念`
- `## 行动启示`
- `## 标签`（如 `#AI #学习方法`）

### 推荐的 Obsidian 插件

| 插件 | 用途 |
|------|------|
| **Dataview** | 用 DQL 查询所有视频笔记，按日期/标签排序 |
| **Tag Wrangler** | 管理 `#标签` |
| **Graph View** | 可视化知识连接 |

Dataview 查询示例（在任意笔记中粘贴）：

````markdown
```dataview
TABLE channel, date, tags
FROM "Videos"
WHERE type = "video-note"
SORT date DESC
```
````

---

## 模型选择

### Claude 模型

修改 `.env` 中的 `CLAUDE_MODEL`：

| 模型 | 速度 | 成本 | 推荐场景 |
|------|------|------|----------|
| `claude-haiku-4-5-20251001` | 最快 | 最低 | 字幕极长、高频处理 |
| `claude-sonnet-4-6` | 快 | 中 | **默认，日常使用** |
| `claude-opus-4-7` | 慢 | 高 | 需要最深度分析时 |

### 嵌入模型

修改 `.env` 中的 `EMBED_MODEL`（首次使用会自动下载）：

| 模型 | 大小 | 中文效果 | 说明 |
|------|------|----------|------|
| `paraphrase-multilingual-MiniLM-L12-v2` | ~470MB | 好 | **默认** |
| `paraphrase-multilingual-mpnet-base-v2` | ~1.1GB | 更好 | 更高搜索质量 |
| `BAAI/bge-m3` | ~2.2GB | 最好 | 中文专用，质量最高 |

> **注意**：更换嵌入模型后，已有的向量索引需要重建。删除 `data/chroma_db` 目录，然后重新处理已有视频。

---

## 常见问题

### Q: YouTube 视频提取失败？

1. 确认 `yt-dlp` 是最新版：`pip install -U yt-dlp`
2. 部分视频可能需要登录才能访问，目前不支持需要登录的私有视频
3. 地区限制的视频可能无法访问

### Q: Bilibili 字幕乱码或为空？

B站很多视频使用 AI 自动字幕，质量参差不齐。如果字幕为空，程序会自动回退到 Whisper 语音识别。

### Q: 向量搜索结果不相关？

1. 尝试更换更好的嵌入模型（如 `BAAI/bge-m3`）
2. 知识库中视频数量少时，搜索范围有限，随着积累会改善
3. 用更具体的关键词提问

### Q: 如何备份知识库？

- **笔记**：直接备份 Obsidian Vault 目录
- **向量索引**：备份 `data/chroma_db` 目录
- **视频列表**：备份 `data/videos.json` 文件

### Q: 如何在多台设备上同步？

Obsidian 笔记可通过 Obsidian Sync、iCloud、Dropbox 等同步。  
ChromaDB 是本地数据库，建议每台设备独立运行，重处理视频时会重建索引。

### Q: 支持哪些视频平台？

通过 `yt-dlp` 支持 1000+ 平台，包括但不限于：
YouTube、Bilibili、Twitter/X、Instagram、TikTok、Vimeo、优酷、爱奇艺（部分）

### Q: API 费用大概多少？

以一个 30 分钟视频为例（~15000 字幕字符）：
- 提炼观点：约 $0.003（Sonnet 4.6）
- 每次对话：约 $0.001
- 月均 50 个视频 + 200 次对话 ≈ **$0.35/月**
