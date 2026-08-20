---
name: setup-project
description: 一键配置「知研 Agent」项目的完整本地环境，适用于 macOS 和 Windows 用户首次部署。检测前置依赖、创建虚拟环境、安装依赖、配置 .env、安装前端依赖并打印启动指引。
argument-hint: "[--skip-frontend] [--skip-env]"
disable-model-invocation: true
allowed-tools: Bash Read Edit Write
---

# 一键配置项目环境

## 当前系统快照

- 操作系统：!`uname -s 2>/dev/null || echo "Windows"`
- Python：!`python3 --version 2>/dev/null || python --version 2>/dev/null || echo "NOT_FOUND"`
- Node.js：!`node --version 2>/dev/null || echo "NOT_FOUND"`
- npm：!`npm --version 2>/dev/null || echo "NOT_FOUND"`
- ffmpeg：!`ffmpeg -version 2>&1 | head -1 2>/dev/null || echo "NOT_FOUND"`
- .venv 状态：!`test -d backend/.venv && echo "EXISTS" || echo "NOT_FOUND"`
- .env 状态：!`test -f backend/.env && echo "EXISTS" || echo "NOT_FOUND"`
- 传入参数：$ARGUMENTS

---

## 执行步骤

### Step 1 — 检查前置依赖

根据快照逐项判断，不满足时立即停止并给出对应系统的安装指引：

**Python（必须 ≥ 3.11）**
- NOT_FOUND 或版本过低：
  - macOS：`brew install python@3.11`
  - Windows：https://python.org/downloads （安装时勾选 "Add to PATH"）
  - 安装后重新运行 `/setup-project`

**Node.js（必须 ≥ 18）**
- NOT_FOUND 或版本过低：
  - macOS：`brew install node`
  - Windows：https://nodejs.org 下载 LTS 版
  - 安装后重新运行 `/setup-project`

**ffmpeg（可选）**
- NOT_FOUND → 仅提示，不中断流程（只影响无字幕视频的 Whisper 识别）：
  - macOS：`brew install ffmpeg`
  - Windows：`winget install ffmpeg`

---

### Step 2 — 创建 Python 虚拟环境

若 .venv 为 NOT_FOUND，执行对应命令：

```bash
# macOS / Linux
python3.11 -m venv backend/.venv || python3 -m venv backend/.venv
```

```powershell
# Windows（PowerShell）
python -m venv backend\.venv
```

已存在则跳过并告知用户。

---

### Step 3 — 安装 Python 依赖

```bash
# macOS / Linux
backend/.venv/bin/pip install --upgrade pip -q
backend/.venv/bin/pip install -r backend/requirements.txt
```

```powershell
# Windows
backend\.venv\Scripts\pip.exe install --upgrade pip -q
backend\.venv\Scripts\pip.exe install -r backend\requirements.txt
```

提醒用户：首次安装会下载 `BAAI/bge-reranker-base`（约 280MB），耐心等待。

---

### Step 4 — 配置 .env 文件

若传入参数包含 `--skip-env`，跳过此步骤。

若 .env 为 NOT_FOUND：
1. 用 Read 工具读取 `backend/.env.example`
2. 逐项询问用户（每项等待回复再继续）：

   | 变量 | 说明 | 必填 |
   |------|------|------|
   | `DEEPSEEK_API_KEY` | DeepSeek API 密钥，从 https://platform.deepseek.com 获取 | 是 |
   | `OBSIDIAN_VAULT` | Obsidian 笔记库绝对路径，如 `/Users/xxx/Documents/Videos` | 是 |
   | `QWEN_API_KEY` | 通义千问密钥（直接回车跳过） | 否 |
   | `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` | 可观测性追踪（直接回车跳过） | 否 |

3. 用 Edit 工具将用户输入写入 `backend/.env`，保留 `.env.example` 的注释结构

若 .env 已存在，询问用户是否需要修改，不需要则跳过。

---

### Step 5 — 创建 Obsidian Vault 目录

读取 `backend/.env` 中 `OBSIDIAN_VAULT` 的值，若目录不存在则创建：

```bash
mkdir -p "<OBSIDIAN_VAULT 实际路径>"
```

---

### Step 6 — 安装前端依赖

若传入参数包含 `--skip-frontend`，跳过此步骤。

```bash
cd frontend && npm install
```

---

### Step 7 — 验证配置

```bash
# macOS / Linux
backend/.venv/bin/python - <<'EOF'
import sys; sys.path.insert(0, 'backend')
from config import DEEPSEEK_API_KEY, OBSIDIAN_VAULT
key_status = '已设置 (' + DEEPSEEK_API_KEY[:6] + '...)' if DEEPSEEK_API_KEY and 'your_' not in DEEPSEEK_API_KEY else '⚠ 未设置'
print('✓ config 加载成功')
print(f'  DEEPSEEK_API_KEY : {key_status}')
print(f'  OBSIDIAN_VAULT   : {OBSIDIAN_VAULT}')
EOF
```

---

### Step 8 — 打印启动指引

**macOS / Linux：**
```bash
# 终端 1 — 后端（http://localhost:8000）
source backend/.venv/bin/activate
python backend/app.py

# 终端 2 — 前端（http://localhost:5173）
cd frontend && npm run dev
```

**Windows（PowerShell）：**
```powershell
# 若提示执行策略报错，先执行：
# Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# 终端 1 — 后端
backend\.venv\Scripts\Activate.ps1
python backend\app.py

# 终端 2 — 前端
cd frontend; npm run dev
```

**（可选）接入 MCP Server for Claude Desktop / Cursor：**

编辑 `~/.claude/claude_desktop_config.json`：
```json
{
  "mcpServers": {
    "knowledge-base": {
      "command": "/项目绝对路径/backend/.venv/bin/python",
      "args": ["/项目绝对路径/backend/mcp_server.py"],
      "env": {
        "DEEPSEEK_API_KEY": "your_key",
        "OBSIDIAN_VAULT": "/your/vault/path"
      }
    }
  }
}
```
