# 个人视频知识库 Agent

把视频链接丢进去，自动提取文案、提炼核心观点、按分类存入 Obsidian，并支持基于知识库的 AI 对话。

## 功能

- **多平台支持**：YouTube、Bilibili、Twitter/X、Vimeo、TikTok 等
- **自动提取文案**：优先使用平台自带字幕，无字幕时自动调用 Whisper 语音识别
- **AI 提炼观点**：通过 DeepSeek 提炼核心摘要、主要观点、关键概念、行动启示
- **自动分类归档**：自动判断视频所属类别（AI与科技 / 财经理财 / 心理学等），存入对应的 Obsidian 文件夹
- **Obsidian 笔记**：每个视频生成一份 Markdown 笔记，包含原始文案和知识提炼
- **RAG 智能问答**：基于已收录的视频知识库进行语义检索和 AI 对话

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python · FastAPI · SSE 实时进度流 |
| 前端 | React · TypeScript · Vite · Tailwind CSS |
| 大模型 | DeepSeek API（OpenAI 兼容格式） |
| 语音识别 | OpenAI Whisper（本地 CPU 推理，兜底方案） |
| 向量存储 | ChromaDB · sentence-transformers 多语言嵌入 |
| 笔记存储 | Obsidian Vault（本地 Markdown 文件） |
| 视频提取 | yt-dlp · bilibili-api-python · youtube-transcript-api |

## 目录结构

```
.
├── backend/
│   ├── app.py                  # FastAPI 主入口
│   ├── config.py               # 环境变量配置
│   ├── requirements.txt
│   ├── extractors/
│   │   ├── youtube.py          # YouTube 字幕提取
│   │   ├── bilibili.py         # B站字幕提取（bilibili_api）
│   │   ├── generic.py          # 其他平台（yt-dlp）
│   │   └── whisper_fallback.py # 无字幕时 Whisper 兜底
│   ├── processors/
│   │   └── insights.py         # DeepSeek 知识提炼 + 分类
│   └── storage/
│       ├── obsidian.py         # 写入 Obsidian Vault
│       ├── vector_store.py     # ChromaDB 向量存储
│       └── video_db.py         # 视频元数据列表
└── frontend/
    └── src/
        ├── components/
        │   ├── VideoInput.tsx   # 视频提交（平台选择 + URL 输入）
        │   ├── VideoLibrary.tsx # 已收录视频列表
        │   └── ChatInterface.tsx# 知识库对话
        └── api/client.ts       # API 请求封装
```

## 快速开始

### 前置条件

- Python 3.11+
- Node.js 18+
- ffmpeg（Whisper 依赖）
- [DeepSeek API Key](https://platform.deepseek.com/)

```bash
# macOS 安装 ffmpeg
brew install ffmpeg
```

### 1. 克隆项目

```bash
git clone https://github.com/YOUR_USERNAME/knowledge-agent.git
cd knowledge-agent
```

### 2. 配置后端

```bash
cd backend

# 创建并激活虚拟环境（Python 3.11）
python3.11 -m venv .venv
source .venv/bin/activate

# 安装依赖（国内可加镜像）
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 配置环境变量
cp .env.example .env
```

编辑 `.env`：

```env
DEEPSEEK_API_KEY=your_deepseek_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
OBSIDIAN_VAULT=/path/to/your/obsidian/vault/Videos
```

### 3. 启动后端

```bash
cd backend
source .venv/bin/activate
python app.py
# 服务运行在 http://localhost:8000
```

### 4. 启动前端

```bash
cd frontend
npm install
npm run dev
# 页面运行在 http://localhost:5173
```

## 使用方式

1. 打开 `http://localhost:5173`
2. 在左侧选择视频平台（YouTube / Bilibili / 其他）
3. 粘贴视频链接，点击「添加」
4. 等待进度条完成（字幕提取 → AI 提炼 → 写入存储）
5. 视频笔记自动保存到 Obsidian 对应分类文件夹
6. 切换到「对话」标签，向知识库提问

## Obsidian 笔记结构

每个视频生成一份笔记，自动存入对应分类文件夹：

```
Vault/
├── AI与科技/
│   └── 2026-01-01 视频标题.md
├── 财经理财/
│   └── 2026-01-01 另一个视频.md
└── 心理学/
    └── ...
```

笔记内容：

```markdown
---
title: "视频标题"
source: "https://..."
channel: "频道名"
category: "AI与科技"
date: 2026-01-01
type: video-note
---

# 视频标题

## 原始文案
（完整字幕 / Whisper 转录文本）

---

## 核心摘要
## 主要观点
## 关键概念
## 行动启示
## 标签
```

## 支持的视频分类

`财经理财` · `AI与科技` · `心理学` · `商业创业` · `健康生活` · `教育学习` · `历史文化` · `娱乐综艺` · `科学探索` · `其他`

分类由 DeepSeek 根据视频内容自动判断。

## 常见问题

**Q: Bilibili 视频没有字幕怎么办？**  
A: 会自动降级到 Whisper 语音识别，CPU 上跑完整视频需要几分钟，属于正常现象。

**Q: 想提升 Whisper 识别速度/精度？**  
A: 在 `.env` 中调整模型大小：`WHISPER_MODEL=tiny`（最快）/ `base`（默认）/ `small` / `medium`。

**Q: 代理环境下遇到 SSL 证书错误？**  
A: 项目已内置全局 SSL 验证跳过，适配企业代理/自签名证书环境。
