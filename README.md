# 个人视频知识库 Agent

把视频链接丢进去，自动提取文案、提炼核心观点、存入向量库和 Obsidian，并支持基于知识库的 AI 对话与多 Agent 深度分析。

## 核心功能

### 知识入库（两步链式思考）
- **多平台支持**：YouTube、Bilibili、Twitter/X、Vimeo、TikTok 等
- **自动提取文案**：优先平台原生字幕，无字幕时自动 Whisper 语音识别兜底
- **笔记导入**：支持导入本地 `.md` / `.txt` 文件，自动向量化入库
- **两步链式录入**：Step 1 分析（提取实体、发现与已有知识的关联、识别矛盾）→ Step 2 生成（写带 `[[wikilink]]` 交叉引用的 Wiki 页面）
- **自动分类归档**：AI 判断类别，写入 Obsidian 对应文件夹
- **知识库定位（Purpose）**：`data/purpose.md` 定义知识库方向，所有录入与问答均参考此上下文

### 智能问答（RAG）
- **意图感知路由**：自动识别时间型（"最近加了什么"）、实体型（"XXX讲了什么"）、概念型三类查询，走不同检索路径
- **Multi-Query 扩展**：概念型查询自动生成 3 个语义变体，多路检索后合并去重，提升召回率
- **混合检索**：ChromaDB 密集向量 + BM25 稀疏检索，RRF 融合排序
- **Query Rewriting**：LLM 改写用户问题，注入知识库定位上下文
- **显著性增强排序**：CrossEncoder × (1 + 0.2 × significance\_score)，高质量内容靠前
- **反思机制（Reflection）**：答案生成后自动检测遗漏点，不足时触发补充搜索
- **带引用的回答**：答案末尾附出处视频/笔记标题
- **对话持久化**：历史消息存入 LocalStorage，切换 Tab 不丢失

### Dream Cycle（后台自主维护）
- **每日凌晨自动运行**（APScheduler 3:17 AM），无需手动触发
- **显著性重算**：综合图谱连接数(40%) + SM-2 复习表现(30%) + 复习次数(20%) + 标签数(10%)
- **断链扫描**：检测 Obsidian 笔记中指向不存在页面的 `[[wikilinks]]`
- **矛盾收集**：汇总知识关联段落中被标注的矛盾观点
- **孤立节点识别**：找出与其他内容关联稀少（degree ≤ 1）的视频
- 报告写入 `data/dream_cycle_report.json`，可通过 API 读取

### 知识图谱
- **force-directed 布局**：自动排布视频节点与共享概念节点
- **缺口检测**：识别孤立节点、意外跨类别连接，LLM 生成针对性研究建议
- **研究缺口**：对每个知识缺口在库内搜索现有相关内容，辅助判断优先级
- **交互**：滚轮缩放、拖拽平移、悬浮高亮关联节点

### 多 Agent 深度分析
- **Orchestrator 并行架构**：ResearchAgent + AnalysisAgent `asyncio.gather` 并行执行，WritingAgent 汇总输出
- **ReAct 循环**：每个子 Agent 独立的思考→工具调用→观察循环（最多 5 步）
- **执行轨迹可视化**：前端实时展示各 Agent 状态与摘要

### Harness Engineering
- **LessonStore**：每次 Agent 失败自动记录「什么错 → 根因 → 怎么改」，持久化到 `data/harness_lessons.json`，让 Agent 永不重蹈同一个错误
- **AgentContextBuilder**：每次运行前把相关 Lesson 注入 system prompt 前缀，Agent 一开始就知道哪些坑要避开
- **Guardrails（自修正版）**：输入输出双向安全检查，每条拦截规则携带 `Fix: ...` 自修正指令，不只是"你被拦了"而是告诉 Agent 怎么改
- **TokenBudget**：per-run 输入/输出/工具调用次数上限，超限即中止
- **Retry + CircuitBreaker**：指数退避抖动重试 + 三态熔断器（closed → open → half-open）
- **Checkpoint**：Agent 运行状态原子落盘，崩溃后可从断点续跑
- **可观测性**：LangFuse 全链路追踪（无 Key 时优雅降级为 no-op）

### Voyager 技能库
- **自动技能提取**：成功运行后 LLM 自动从 transcript 中提炼可复用技能
- **TF-IDF 语义检索**：新任务启动时自动召回相关技能，注入 Agent 上下文
- **持久化管理**：技能 JSON 落盘，前端可查看/删除

### 其他能力
- **主动回忆（Spaced Repetition）**：SM-2 算法生成复习卡片
- **长期记忆**：跨会话用户兴趣与知识空白画像
- **深度研究**：多 Agent 检索、对抗校验、断点恢复与报告导出
- **RAG 评测体系**：LLM-as-Judge 自动生成测试集，评测 Faithfulness / Answer Relevancy / Precision@3
- **统计面板**：视频数量、内容时长、分类分布、高频标签、周趋势

## 系统架构

```
用户请求
  │
  ▼
FastAPI (SSE 流式响应)
  │
  ├─ Guardrails ──── 输入安全检查（含 Fix 自修正指令）
  ├─ TokenBudget ─── 资源限制
  ├─ CircuitBreaker ─ 熔断保护
  │
  ▼
AgentHarness（Harness Engineering 核心）
  ├─ LessonStore ──── 失败学习：记录错误 + 根因 + 修复方案
  ├─ AgentContext ─── 运行前注入相关 Lesson 到 system prompt
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

知识录入链路（两步）：
  字幕 → [Step 1] 分析（实体/关联/矛盾/缺口 → JSON）
       → [Step 2] 生成（Wiki 页 + [[wikilinks]] + 待研究缺口）
       → Obsidian + ChromaDB + BM25

RAG 检索链路：
  Query → 意图分类 → 时间型: 按 created_at 排序返回
                   → 实体型: 单路检索
                   → 概念型: Multi-Query 扩展(×3) → 多路搜索合并
         → ChromaDB + BM25 (每路15) → 去重合并
         → CrossEncoder × Significance Boost (top 6)
         → 反思检查 → 补充搜索（可选）→ 带引用答案

Dream Cycle（每日 03:17）：
  显著性重算 → 断链扫描 → 矛盾收集 → 孤立节点识别 → 报告落盘
```

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | Python 3.11 · FastAPI · SSE 实时流 |
| 前端 | React 18 · TypeScript · Vite · Tailwind CSS |
| 大模型 | DeepSeek API（OpenAI 兼容格式）· 通义千问（可选） |
| 语音识别 | OpenAI Whisper（本地 CPU 推理） |
| 向量存储 | ChromaDB · sentence-transformers 多语言嵌入 |
| 稀疏检索 | BM25（rank-bm25） |
| 精排模型 | BAAI/bge-reranker-base（CrossEncoder） |
| 可观测性 | LangFuse（cloud.langfuse.com） |
| 笔记存储 | Obsidian Vault（本地 Markdown） |
| 视频提取 | yt-dlp · bilibili-api-python · youtube-transcript-api |
| 定时任务 | APScheduler（每周复盘 + 每日 Dream Cycle） |

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
│   ├── harness/                    # Harness Engineering 基础设施
│   │   ├── agent_harness.py        # AgentHarness（组合所有组件，含 .default() 工厂）
│   │   ├── lessons.py              # LessonStore：失败学习，永不重蹈同一错误
│   │   ├── context.py              # AgentContextBuilder：运行前注入 Lesson 上下文
│   │   ├── budget.py               # TokenBudget
│   │   ├── checkpoint.py           # 断点续跑
│   │   ├── guardrails.py           # 输入输出安全检查（含 Fix 自修正指令）
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
│   │   ├── insights.py             # 两步链式知识提炼（分析→Wiki页）
│   │   ├── rag_enhancer.py         # Multi-Query扩展 + 意图分类 + Reranking
│   │   ├── knowledge_graph.py      # 图谱构建 + 缺口检测
│   │   ├── purpose_manager.py      # 知识库定位文件管理
│   │   ├── significance.py         # 显著性评分计算
│   │   ├── dream_cycle.py          # 后台自主维护任务
│   │   └── review.py               # 每周复盘生成
│   ├── extractors/
│   │   ├── youtube.py
│   │   ├── bilibili.py
│   │   ├── generic.py              # yt-dlp 通用提取
│   │   └── whisper_fallback.py
│   └── storage/
│       ├── vector_store.py         # ChromaDB + 句子级分块
│       ├── bm25_store.py           # BM25 稀疏索引
│       ├── obsidian.py             # Obsidian Vault 写入
│       └── video_db.py             # 视频元数据 + 显著性分数
└── frontend/
    └── src/
        ├── components/
        │   ├── AgentPanel.tsx       # 深度分析
        │   ├── ChatInterface.tsx    # RAG 对话（带引用 + 反思）
        │   ├── EvalPanel.tsx        # RAG 评测面板
        │   ├── GraphPanel.tsx       # 知识图谱（force-directed）
        │   ├── MemorySidebar.tsx    # 长期记忆
        │   ├── NoteImportPanel.tsx  # 本地笔记导入
        │   ├── RecallPanel.tsx      # 主动回忆（SM-2）
        │   ├── ReviewPanel.tsx      # 每周复盘
        │   ├── StatsPanel.tsx       # 统计 + 评测
        │   └── VideoInput.tsx       # 视频提交
        ├── api/client.ts            # 所有 API 请求
        └── types/index.ts           # 类型定义
skills/
└── setup-project.md                # /setup-project：一键配置 macOS / Windows 环境
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
DEEPSEEK_MODEL=deepseek-v4-flash
DEEP_RESEARCH_DRAFT_MODEL=deepseek-v4-flash
DEEP_RESEARCH_SUPERVISOR_MODEL=deepseek-v4-flash
DEEP_RESEARCH_RESEARCHER_MAIN_MODEL=deepseek-v4-flash
DEEP_RESEARCH_RESEARCHER_SUMMARIZER_MODEL=deepseek-v4-flash
DEEP_RESEARCH_RESEARCHER_COMPRESSOR_MODEL=deepseek-v4-flash
DEEP_RESEARCH_RED_TEAM_MODEL=deepseek-v4-pro
DEEP_RESEARCH_EVALUATOR_MODEL=deepseek-v4-pro
DEEP_RESEARCH_WRITER_MODEL=deepseek-v4-pro
DEEP_RESEARCH_LLM_TIMEOUT_SECONDS=120
DEEP_RESEARCH_MAX_ITERATIONS=15
OBSIDIAN_VAULT=/path/to/vault/Videos

# 可选：通义千问（用于模型切换）
QWEN_API_KEY=your_key
QWEN_MODEL=qwen-plus

# 可选：LangFuse 可观测性（不填则静默跳过）
LANGFUSE_PUBLIC_KEY=pk-lf-xxx
LANGFUSE_SECRET_KEY=sk-lf-xxx
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

```bash
python app.py
# http://localhost:8000
```

DeepResearch 现在使用 LangGraph 类型化状态图运行。每次运行以 `run_id` 作为
checkpoint `thread_id`，节点状态持久化到 `backend/data/deep_research_checkpoints.sqlite`；
使用相同 `run_id` 重试会从未完成节点继续。研究资料被保存为结构化 Evidence，最终
报告拆分为 Claim/Citation 后校验，未出现在本次证据集中的链接会被移除。

运行期间会按角色和工具记录真实 token、调用次数及费用。费用计算需要在 `.env` 中
填写对应模型的 `*_PER_MILLION_USD`，保持为 `0` 时只统计 token、不虚构供应商价格。
可调用 `POST /api/agent/deep-run/{run_id}/cancel` 主动取消；浏览器断开连接也会取消正在
等待的模型请求。完整质量门禁可运行：

```bash
cd backend
.venv/Scripts/python -m pytest -q
```

### 2. 前端

```bash
cd frontend
npm install
npm run dev
# http://localhost:5173
```

### 3. 配置知识库定位（可选但推荐）

在 `backend/data/purpose.md` 中描述你的知识库方向：

```markdown
# 知识库定位

## 目标描述
专注于 AI 技术、商业创业、个人成长领域的深度学习。

## 关键问题
- AI Agent 如何在实际业务中落地？
- 创业公司如何在资源有限时高效增长？

## 研究范围
重点：AI/ML、创业方法论、个人效率
排除：娱乐内容、新闻时事
```

或直接调用 `POST /api/purpose` 接口写入。

## API 路由

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/process-video` | 提交视频处理（返回 task_id） |
| GET | `/api/status/{task_id}` | SSE 进度流 |
| GET | `/api/videos` | 视频列表 |
| DELETE | `/api/videos/{id}` | 删除视频 |
| POST | `/api/chat/stream` | RAG 对话（SSE 流式） |
| POST | `/api/agent/run` | 多 Agent 深度分析（SSE 流式） |
| GET | `/api/graph` | 知识图谱数据 |
| POST | `/api/graph/rebuild` | 强制重建图谱 |
| GET | `/api/graph/gaps` | 检测知识缺口 |
| POST | `/api/graph/research-gap` | 在库内搜索某缺口的现有内容 |
| GET | `/api/purpose` | 读取知识库定位 |
| POST | `/api/purpose` | 更新知识库定位 |
| GET | `/api/dream-cycle/report` | 读取最近一次 Dream Cycle 报告 |
| POST | `/api/dream-cycle/run` | 手动触发 Dream Cycle |
| GET | `/api/skills` | 技能库列表 |
| DELETE | `/api/skills/{id}` | 删除技能 |
| GET | `/api/harness/status` | 熔断器状态 |
| POST | `/api/evals/generate` | 生成 RAG 测试集 |
| POST | `/api/evals/run` | 运行 RAG 评测 |
| GET | `/api/evals/results` | 最近评测结果 |
| GET | `/api/stats` | 知识库统计 |
| GET | `/api/memory` | 长期用户记忆 |

## RAG 评测指标

系统内置 LLM-as-Judge 评测框架，无需手标数据：

| 指标 | 说明 | 目标 |
|------|------|------|
| Faithfulness | 回答是否忠实于检索到的上下文 | ≥ 0.80 |
| Answer Relevancy | 回答是否切题 | ≥ 0.75 |
| Precision@3 | 检索 top-3 命中率 | ≥ 0.70 |

## Harness 组件说明

```
AgentHarness（Harness Engineering）
├─ LessonStore        # 失败学习：错误 → 根因 → Fix，持久化到 data/harness_lessons.json
├─ AgentContextBuilder # 运行前注入相关 Lesson，Agent 开局即知哪些坑要避
├─ Guardrails         # 正则拦截 prompt 注入 / 敏感数据，每条规则携带 Fix 指令
├─ TokenBudget        # 输入 80k / 输出 20k / 工具调用 30 次
├─ CircuitBreaker     # 5 次连续失败 → open，60s 后 half-open 探测
├─ RetryPolicy        # 最多 2 次重试，指数退避 ± 15% 抖动
└─ CheckpointStore    # JSON 落盘，data/checkpoints/
```

## 常见问题

### 中国公募基金 Deep Research 配置

项目内置 `cn-fund-research` 文件型 Agent Skill。基金或 ETF 任务使用 Tavily 搜索基金公司、
交易所、监管机构、指数公司和定期报告等公开资料，并经过 Evidence 与 Red Team 口径校验。
不再调用需要付费 Token 的金融数据接口。请在 `backend/.env` 配置：

```env
CN_FUND_ENABLE_WEB_SEARCH=true
CN_FUND_ANNUAL_RISK_FREE_RATE=0.015
CN_FUND_DEFAULT_BENCHMARK=

TAVILY_API_KEY=你的_Tavily_API_Key
TAVILY_BASE_URL=https://api.tavily.com
```

`CN_FUND_DEFAULT_BENCHMARK` 建议留空，由产品官方披露、研究计划或用户明确指定。
公开网页没有完整、同口径、可按日期对齐的历史序列时，报告会明确披露数据不足，
不会通过模型心算生成收益、回撤或风险指标。

修改 `.env` 后重启 FastAPI。可用“研究 510300 最近三年，对比沪深300，区分场内价格、
净值与复权口径，并列出来源页面、数据口径和截止日期”进行验证。

**Q: Bilibili 视频没有字幕？**  
A: 自动降级 Whisper，CPU 跑完整视频需几分钟，属正常。`WHISPER_MODEL=tiny` 可加速。

**Q: LangFuse 没有 Key 怎么办？**  
A: 不填即可，Tracer 自动切为 no-op，不影响任何功能。

**Q: 企业代理 / SSL 证书报错？**  
A: 项目已内置全局 SSL 验证跳过，适配自签名证书环境。

**Q: CrossEncoder 首次加载很慢？**  
A: `BAAI/bge-reranker-base` 约 280MB，首次从 HuggingFace 下载后本地缓存，后续秒级加载。

**Q: Harness Engineering 是什么，和运行时中间件有什么区别？**  
A: Harness Engineering（Mitchell Hashimoto 2026 年提出）的核心是：每次 Agent 犯错，就工程化地让它永不再犯。`LessonStore` 记录每次失败的根因和 Fix，`AgentContextBuilder` 在下次运行前把相关 Lesson 注入 system prompt。运行时中间件（retry / circuit breaker / budget）只管"这次跑"，Harness Engineering 管的是"跨次学习"。

**Q: Lesson 存在哪里，怎么查看？**  
A: 持久化在 `data/harness_lessons.json`，可通过 `GET /api/harness/status` 查看熔断器状态，Lesson 内容直接读 JSON 文件或扩展 API 接口。

**Q: Dream Cycle 什么时候运行？**  
A: 每天凌晨 3:17 自动运行，也可调用 `POST /api/dream-cycle/run` 手动触发。报告通过 `GET /api/dream-cycle/report` 查看。

**Q: 两步链式录入会不会更慢？**  
A: 多一次 LLM 分析调用（约 2-3 秒），但生成的 Wiki 页质量更高，并自动与已有内容建立 `[[wikilinks]]` 关联。首次录入（库为空）时两步几乎无差异。

**Q: 知识库定位（Purpose）有什么用？**  
A: 定义 purpose 后，录入时 LLM 会在该方向下提炼观点（而不是泛泛总结），问答时 query rewriting 也会根据方向扩展语义，显著减少跑偏回答。
