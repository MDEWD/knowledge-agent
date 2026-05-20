# 个人视频知识库 Agent

把视频链接丢进去，自动提取文案、提炼核心观点、存入向量库和 Obsidian，并支持基于知识库的 AI 对话与多 Agent 深度分析。

## 核心功能

### 知识入库
- **多平台支持**：YouTube、Bilibili、Twitter/X、Vimeo、TikTok 等
- **自动提取文案**：优先平台原生字幕，无字幕时自动 Whisper 语音识别兜底
- **笔记导入**：支持导入本地 `.md` / `.txt` 文件，自动向量化入库
- **AI 提炼观点**：DeepSeek 自动生成摘要、主要观点、关键概念、行动启示
- **自动分类归档**：AI 判断类别，写入 Obsidian 对应文件夹

### 智能问答（RAG）
- **混合检索**：ChromaDB 密集向量 + BM25 稀疏检索，RRF 融合排序
- **Query Rewriting**：LLM 改写用户问题，扩展语义、补全隐含背景
- **Cross-Encoder Reranking**：`BAAI/bge-reranker-base` 精排 top-k，中英双语
- **反思机制（Reflection）**：答案生成后自动检测遗漏点，不足时触发补充搜索
- **带引用的回答**：答案末尾附出处视频/笔记标题
- **对话持久化**：历史消息存入 LocalStorage，切换 Tab 不丢失

### 多 Agent 深度分析
- **Orchestrator 并行架构**：ResearchAgent + AnalysisAgent `asyncio.gather` 并行执行，WritingAgent 汇总输出
- **ReAct 循环**：每个子 Agent 独立的思考→工具调用→观察循环（最多 5 步）
- **执行轨迹可视化**：前端实时展示各 Agent 状态与摘要

### Harness 运行时基础设施（Agent = Model + Harness）
- **Guardrails**：输入输出双向安全检查（prompt 注入检测 + 敏感数据扫描）
- **TokenBudget**：per-run 输入/输出/工具调用次数上限，超限即中止
- **Retry + CircuitBreaker**：指数退避抖动重试 + 三态熔断器（closed → open → half-open）
- **Checkpoint**：Agent 运行状态原子落盘，崩溃后可从断点续跑
- **可观测性**：LangFuse 全链路追踪（无 Key 时优雅降级为 no-op）

### Voyager 技能库（Skill Library）
- **自动技能提取**：成功运行后 LLM 自动从 transcript 中提炼可复用技能
- **TF-IDF 语义检索**：新任务启动时自动召回相关技能，注入 Agent 上下文
- **持久化管理**：技能 JSON 落盘，前端可查看/删除

### 其他能力
- **主动回忆（Spaced Repetition）**：SM-2 算法生成复习卡片
- **知识图谱**：force-directed 图谱展示视频与概念关联
- **长期记忆**：跨会话用户兴趣与知识空白画像
- **综合文章生成**：跨视频主题文章自动撰写
- **RAG 评测体系**：LLM-as-Judge 自动生成测试集，评测 Faithfulness / Answer Relevancy / Precision@3
- **统计面板**：视频数量、内容时长、分类分布、高频标签、周趋势

## 系统架构

```
用户请求
  │
  ▼
FastAPI (SSE 流式响应)
  │
  ├─ Guardrails ──── 输入安全检查
  ├─ TokenBudget ─── 资源限制
  ├─ CircuitBreaker ─ 熔断保护
  │
  ▼
OrchestratorAgent
  ├─ ResearchAgent  ──┐
  │  (RAG 检索)       ├── asyncio.gather 并行
  ├─ AnalysisAgent  ──┘
  │  (对比分析)
  └─ WritingAgent
     (综合报告 · 流式输出)
  │
  ├─ SkillExtractor ─ 提取技能 → SkillStore
  └─ LangFuse Tracer ─ 全链路追踪

RAG 检索链路：
  Query → LLM Rewrite → ChromaDB + BM25 (召回 20) → CrossEncoder Rerank (top 6)
       → 反思检查 → 补充搜索（可选）→ 带引用答案
```

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | Python 3.11 · FastAPI · SSE 实时流 |
| 前端 | React 18 · TypeScript · Vite · Tailwind CSS |
| 大模型 | DeepSeek API（OpenAI 兼容格式） |
| 语音识别 | OpenAI Whisper（本地 CPU 推理） |
| 向量存储 | ChromaDB · sentence-transformers 多语言嵌入 |
| 稀疏检索 | BM25（rank-bm25） |
| 精排模型 | BAAI/bge-reranker-base（CrossEncoder） |
| 可观测性 | LangFuse（cloud.langfuse.com） |
| 笔记存储 | Obsidian Vault（本地 Markdown） |
| 视频提取 | yt-dlp · bilibili-api-python · youtube-transcript-api |
| 定时任务 | APScheduler（每周自动复盘） |

## 目录结构

```
.
├── backend/
│   ├── app.py                      # FastAPI 主入口，所有 API 路由
│   ├── config.py                   # 环境变量配置
│   ├── requirements.txt
│   ├── agents/                     # 多 Agent 系统
│   │   ├── base_agent.py           # BaseAgent（ReAct 循环）
│   │   ├── research_agent.py       # 知识库检索
│   │   ├── analysis_agent.py       # 对比分析
│   │   ├── writing_agent.py        # 报告撰写
│   │   └── orchestrator.py         # 并行编排 + 流式输出
│   ├── harness/                    # 运行时基础设施
│   │   ├── agent_harness.py        # AgentHarness（组合所有组件）
│   │   ├── budget.py               # TokenBudget + BudgetExceededError
│   │   ├── checkpoint.py           # CheckpointStore（断点续跑）
│   │   ├── guardrails.py           # 输入输出安全检查
│   │   └── retry.py                # RetryPolicy + CircuitBreaker
│   ├── skills/                     # Voyager 技能库
│   │   ├── skill_store.py          # 持久化 + TF-IDF 检索
│   │   └── skill_extractor.py      # LLM 自动提取技能
│   ├── evals/                      # RAG 评测体系
│   │   ├── eval_rag.py             # LLM-as-Judge 评测指标
│   │   └── generate_test_cases.py  # 自动生成测试集
│   ├── observability/
│   │   └── tracer.py               # LangFuse 封装（no-op 降级）
│   ├── processors/
│   │   ├── insights.py             # 知识提炼 + 分类
│   │   ├── rag_enhancer.py         # Query Rewriting + CrossEncoder Reranking
│   │   └── review.py               # 每周复盘生成
│   ├── extractors/
│   │   ├── youtube.py
│   │   ├── bilibili.py
│   │   ├── generic.py              # yt-dlp 通用提取
│   │   └── whisper_fallback.py
│   └── storage/
│       ├── vector_store.py         # ChromaDB + add_note_document（句子级分块）
│       ├── bm25_store.py           # BM25 稀疏索引
│       ├── obsidian.py
│       └── video_db.py
└── frontend/
    └── src/
        ├── components/
        │   ├── AgentPanel.tsx       # 深度分析（技能库 + Harness 遥测）
        │   ├── ChatInterface.tsx    # RAG 对话（带引用 + 反思标签）
        │   ├── EvalPanel.tsx        # RAG 评测面板
        │   ├── GraphPanel.tsx       # 知识图谱
        │   ├── MemorySidebar.tsx    # 长期记忆
        │   ├── NoteEditor.tsx       # 笔记编辑
        │   ├── NoteImportPanel.tsx  # 本地笔记导入
        │   ├── RecallPanel.tsx      # 主动回忆（SM-2）
        │   ├── ReviewPanel.tsx      # 每周复盘
        │   ├── StatsPanel.tsx       # 统计 + 评测
        │   └── VideoInput.tsx       # 视频提交
        ├── api/client.ts            # 所有 API 请求
        └── types/index.ts           # 类型定义
```

## 快速开始

### 前置条件

- Python 3.11+
- Node.js 18+
- ffmpeg（Whisper 依赖）
- [DeepSeek API Key](https://platform.deepseek.com/)

```bash
# macOS
brew install ffmpeg
```

### 1. 后端

```bash
cd backend

python3.11 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env   # 编辑填入 Key
```

`.env` 示例：

```env
DEEPSEEK_API_KEY=your_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
OBSIDIAN_VAULT=/path/to/vault/Videos

# 可选：LangFuse 可观测性（不填则静默跳过）
LANGFUSE_PUBLIC_KEY=pk-lf-xxx
LANGFUSE_SECRET_KEY=sk-lf-xxx
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

```bash
python app.py
# http://localhost:8000
```

### 2. 前端

```bash
cd frontend
npm install
npm run dev
# http://localhost:5173
```

## API 路由

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/process-video` | 提交视频处理（返回 task_id） |
| GET | `/api/status/{task_id}` | SSE 进度流 |
| GET | `/api/videos` | 视频列表 |
| DELETE | `/api/videos/{id}` | 删除视频 |
| POST | `/api/chat` | RAG 对话（SSE 流式） |
| POST | `/api/agent/run` | 多 Agent 深度分析（SSE 流式） |
| GET | `/api/skills` | 技能库列表 |
| DELETE | `/api/skills/{id}` | 删除技能 |
| GET | `/api/harness/status` | 熔断器状态 |
| POST | `/api/evals/generate` | 生成 RAG 测试集 |
| POST | `/api/evals/run` | 运行 RAG 评测 |
| GET | `/api/evals/results` | 最近评测结果 |
| GET | `/api/stats` | 知识库统计 |
| GET | `/api/memory` | 长期用户记忆 |
| GET | `/api/graph` | 知识图谱数据 |

## RAG 评测指标

系统内置 LLM-as-Judge 评测框架，无需手标数据：

| 指标 | 说明 | 目标 |
|------|------|------|
| Faithfulness | 回答是否忠实于检索到的上下文 | ≥ 0.80 |
| Answer Relevancy | 回答是否切题 | ≥ 0.75 |
| Precision@3 | 检索 top-3 命中率 | ≥ 0.70 |

## Harness 组件说明

```
AgentHarness
├── Guardrails        # 正则拦截 prompt 注入 / 敏感数据泄露
├── TokenBudget       # 输入 80k / 输出 20k / 工具调用 30 次
├── CircuitBreaker    # 5 次连续失败 → open，60s 后 half-open 探测
├── RetryPolicy       # 最多 2 次重试，指数退避 ± 15% 抖动
└── CheckpointStore   # JSON 落盘，data/checkpoints/
```

## 常见问题

**Q: Bilibili 视频没有字幕？**  
A: 自动降级 Whisper，CPU 跑完整视频需几分钟，属正常。`WHISPER_MODEL=tiny` 可加速。

**Q: LangFuse 没有 Key 怎么办？**  
A: 不填即可，Tracer 自动切为 no-op，不影响任何功能。

**Q: 企业代理 / SSL 证书报错？**  
A: 项目已内置全局 SSL 验证跳过，适配自签名证书环境。

**Q: CrossEncoder 首次加载很慢？**  
A: `BAAI/bge-reranker-base` 约 280MB，首次从 HuggingFace 下载后本地缓存，后续秒级加载。

**Q: 技能库是什么，怎么用？**  
A: 每次深度分析成功后，LLM 自动从执行轨迹中提炼可复用的解题模式保存为"技能"。下次执行相似任务时，系统自动召回相关技能注入 Agent 上下文，提升回答质量（类 Voyager 机制）。
