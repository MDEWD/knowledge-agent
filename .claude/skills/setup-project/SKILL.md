---
name: setup-project
description: 一键配置「个人视频知识库 Agent」项目的完整环境，适用于 macOS 和 Windows 用户首次部署，包含 Python 环境、依赖安装、.env 配置、前端依赖安装和启动指引。当用户需要初始化项目、配置环境、首次部署时使用。
argument-hint: "[--skip-frontend] [--skip-env]"
disable-model-invocation: true
allowed-tools: Bash Read Edit Write
---

# 一键配置项目环境

## 当前环境快照

- 操作系统：!`uname -s 2>/dev/null || echo "Windows"`
- Python：!`python3 --version 2>/dev/null || python --version 2>/dev/null || echo "NOT_FOUND"`
- Node.js：!`node --version 2>/dev/null || echo "NOT_FOUND"`
- npm：!`npm --version 2>/dev/null || echo "NOT_FOUND"`
- ffmpeg：!`ffmpeg -version 2>&1 | head -1 2>/dev/null || echo "NOT_FOUND"`
- .venv：!`test -d backend/.venv && echo "EXISTS" || echo "NOT_FOUND"`
- backend/.env：!`test -f backend/.env && echo "EXISTS" || echo "NOT_FOUND"`
- 传入参数：$ARGUMENTS

---

## 执行步骤

### Step 1 — 检查前置依赖

根据上方快照逐项判断，存在问题时立即停止并给出对应系统的安装方式：

**Python（必须 ≥ 3.11）**
- NOT_FOUND 或版本过低 →
  - macOS：`brew install python@3.11`
  - Windows：https://python.org/downloads （安装时勾选 "Add to PATH"）
  - 安装完毕后重新运行 `/setup-project`

**Node.js（必须 ≥ 18）**
- NOT_FOUND 或版本过低 →
  - macOS：`brew install node`
  - Windows：https://nodejs.org 下载 LTS 版
  - 安装完毕后重新运行 `/setup-project`

**ffmpeg（可选，仅影响无字幕视频的 Whisper 语音识别）**
- NOT_FOUND → 提示但不阻断流程：
  - macOS：`brew install ffmpeg`
  - Windows：`winget install ffmpeg`

Python 或 Node.js 不满足要求时，停止本次配置，提示用户安装后重新运行。

---

### Step 2 — 创建 Python 虚拟环境

若 .venv 为 NOT_FOUND，执行：

```bash
# macOS / Linux
python3.11 -m venv backend/.venv || python3 -m venv backend/.venv
```

```powershell
# Windows（PowerShell）
python -m venv backend\.venv
```

已存在则跳过，告知用户。

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

若传入 `--skip-env` 则跳过此步骤。

若 backend/.env 为 NOT_FOUND：

1. 用 Read 工具读取 `backend/.env.example`
2. 逐项询问用户（每项等待回复后再继续）：

   | 变量 | 说明 | 是否必填 |
   |------|------|---------|
   | `DEEPSEEK_API_KEY` | DeepSeek 密钥，从 https://platform.deepseek.com 获取 | 必填 |
   | `OBSIDIAN_VAULT` | Obsidian 笔记库绝对路径，如 `/Users/xxx/Documents/Videos` | 必填 |
   | `QWEN_API_KEY` | 通义千问密钥（可选，直接回车跳过） | 可选 |
   | `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` | 可观测性追踪（可选） | 可选 |

3. 用 Edit 工具将用户输入写入 `backend/.env`，保留原始注释结构

若 backend/.env 已存在，询问用户是否需要修改关键字段，不需要则跳过。

---

### Step 5 — 创建 Obsidian Vault 目录

读取 `backend/.env` 中 `OBSIDIAN_VAULT` 的值，若路径不存在则创建：

```bash
mkdir -p "$OBSIDIAN_VAULT_PATH"
```

---

### Step 6 — 安装前端依赖

若传入 `--skip-frontend` 则跳过此步骤。

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
print("✓ config 加载成功")
print(f"  DEEPSEEK_API_KEY : {'已设置 (' + DEEPSEEK_API_KEY[:6] + '...)' if DEEPSEEK_API_KEY and 'your_' not in DEEPSEEK_API_KEY else '⚠ 未设置'}")
print(f"  OBSIDIAN_VAULT   : {OBSIDIAN_VAULT}")
from storage.vector_store import search
print("✓ vector_store 模块正常")
EOF
```

---

### Step 8 — 打印启动指引

配置全部完成后，输出以下内容：

---

**环境配置完成！**

**macOS / Linux 启动方式：**
```bash
# 终端 1 — 后端（http://localhost:8000）
source backend/.venv/bin/activate
python backend/app.py

# 终端 2 — 前端（http://localhost:5173）
cd frontend && npm run dev
```

**Windows 启动方式（PowerShell）：**
```powershell
# 若提示执行策略报错，先执行：
# Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# 终端 1 — 后端
backend\.venv\Scripts\Activate.ps1
python backend\app.py

# 终端 2 — 前端
cd frontend; npm run dev
```

**（可选）接入 Claude Desktop / Cursor MCP：**

编辑 `~/.claude/claude_desktop_config.json`：
```json
{
  "mcpServers": {
    "knowledge-base": {
      "command": "/绝对路径/backend/.venv/bin/python",
      "args": ["/绝对路径/backend/mcp_server.py"],
      "env": {
        "DEEPSEEK_API_KEY": "your_key",
        "OBSIDIAN_VAULT": "/your/vault/path"
      }
    }
  }
}
```

Windows 路径格式：`C:\\Users\\xxx\\project\\backend\\.venv\\Scripts\\python.exe`
