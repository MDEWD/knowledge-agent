#!/usr/bin/env bash
# 知研 Agent 一键部署脚本（目标：Ubuntu 22.04 服务器）
#
# 用法（在项目根目录执行）：
#   sudo bash deploy.sh <你的域名> [管理员邮箱]
# 例如：
#   sudo bash deploy.sh research.example.com admin@example.com
#
# 前置：代码已上传到服务器（git clone 或 scp），本脚本在项目根目录运行。

set -euo pipefail

DOMAIN="${1:-}"
ADMIN_EMAIL="${2:-}"

if [ -z "$DOMAIN" ]; then
  echo "用法: sudo bash deploy.sh <域名> [管理员邮箱]" >&2
  exit 1
fi

echo "==> 1/6 检查 Docker"
if ! command -v docker >/dev/null 2>&1; then
  echo "    安装 Docker ..."
  curl -fsSL https://get.docker.com | sh
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "    安装 docker compose 插件 ..."
  apt-get update -y && apt-get install -y docker-compose-plugin
fi

cd "$(dirname "$0")"

echo "==> 2/6 准备 .env"
if [ ! -f .env ]; then
  if [ -f .env.production ]; then
    cp .env.production .env
  else
    cat > .env <<'ENVEOF'
# 由 deploy.sh 自动生成，请补全 API 密钥与 SMTP
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash

MYSQL_ROOT_PASSWORD=change-this-root-password
MYSQL_USER=zhiyan
MYSQL_PASSWORD=change-this-app-password

AUTH_SECRET_KEY=replace_with_a_long_random_secret
AUTH_COOKIE_SECURE=true
AUTH_ADMIN_EMAILS=

DOMAIN=your-domain.com
CORS_ORIGINS=https://your-domain.com

SMTP_HOST=smtp.qq.com
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM_EMAIL=
SMTP_FROM_NAME=知研 Agent
SMTP_USE_TLS=true
SMTP_USE_SSL=false

SEARCH_BACKEND=web_only
TAVILY_API_KEY=

EMBED_LOCAL_FILES_ONLY=false
HF_ENDPOINT=https://hf-mirror.com

SSL_NO_VERIFY=false
DEEP_RESEARCH_MAX_COST_USD=5
ENVEOF
  fi
fi

# 工具函数：无条件设置某个 key（存在则替换，不存在则追加）
set_env() {
  local key="$1" value="$2"
  if grep -qE "^${key}=" .env; then
    sed -i -E "s|^${key}=.*|${key}=${value}|" .env
  else
    printf '%s=%s\n' "$key" "$value" >> .env
  fi
}

# 工具函数：生成随机 hex（无特殊字符）
rand() { openssl rand -hex "$1"; }

echo "==> 3/6 写入域名与安全项"
set_env DOMAIN "$DOMAIN" .env
set_env CORS_ORIGINS "https://${DOMAIN}" .env
if [ -n "$ADMIN_EMAIL" ]; then
  set_env AUTH_ADMIN_EMAILS "$ADMIN_EMAIL" .env
fi

# 占位符或为空时才生成，避免覆盖已有真实值
gen_if_placeholder() {
  local key="$1" len="$2" current
  current="$(grep -E "^${key}=.*" .env | head -n1 | cut -d= -f2-)"
  case "$current" in
    ""|"replace_with_a_long_random_secret"|"change-this-root-password"|"change-this-app-password")
      set_env "$key" "$(rand "$len")"
      ;;
  esac
}
gen_if_placeholder AUTH_SECRET_KEY 48
gen_if_placeholder MYSQL_ROOT_PASSWORD 24
gen_if_placeholder MYSQL_PASSWORD 24

echo "==> 4/6 检查必填项"
missing=0
for key in DEEPSEEK_API_KEY TAVILY_API_KEY SMTP_USERNAME SMTP_PASSWORD; do
  val="$(grep -E "^${key}=.*" .env | head -n1 | cut -d= -f2-)"
  if [ -z "$val" ]; then
    echo "    ⚠ ${key} 未填写"
    missing=1
  fi
done
if [ "$missing" -eq 1 ]; then
  echo "    请编辑 .env 补全上述项（注册验证码邮件依赖 SMTP），然后重新运行本脚本"
  echo "    或补全后直接执行: docker compose up -d --build"
fi

echo "==> 5/6 构建并启动（首次会拉取镜像、下载依赖，需几分钟）"
docker compose up -d --build

echo "==> 6/6 状态"
docker compose ps

echo ""
echo "部署完成！"
echo "  访问地址: https://${DOMAIN}"
echo "  查看日志: docker compose logs -f app caddy"
echo "  首次启动会下载 embedding 模型（约 500MB），请耐心等待几分钟"
