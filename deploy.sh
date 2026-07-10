#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# SecKB 一键部署脚本
# 适用系统: Ubuntu 22.04 / 24.04 LTS
#
# 用法:
#   cd /你的项目目录 && sudo ./deploy.sh            ← 直接当前目录部署（推荐）
#   或者远程拉取: sudo ./deploy.sh                     ← 从 GitHub 克隆
# ============================================================

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn() { echo -e "${RED}[WARN]${NC}  $*"; }
step() { echo -e "${CYAN}[STEP]${NC} $*"; }

# ---------- 配置 ----------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 如果有 .env / requirements.txt / app/backend/main.py 说明是项目根目录
if [ -f "$SCRIPT_DIR/requirements.txt" ] && [ -f "$SCRIPT_DIR/app/backend/main.py" ]; then
    # ----- 直接在当前目录部署 -----
    APP_DIR="$SCRIPT_DIR"
    APP_USER="${APP_USER:-root}"
    log "检测到当前目录是项目根目录，直接原地部署"
    log "项目目录: $APP_DIR"
else
    # ----- 从 GitHub 克隆 -----
    APP_DIR="${APP_DIR:-/opt/seckb}"
    APP_USER="${APP_USER:-seckb}"
    GIT_REPO="${GIT_REPO:-https://github.com/shihuizhang-dazhi/rag}"

    step "克隆项目..."
    rm -rf "$APP_DIR"
    git clone --depth 1 "$GIT_REPO" "$APP_DIR"
    log "代码已克隆到 $APP_DIR"
fi

DOMAIN="${DOMAIN:-_}"
NGINX_PORT="${NGINX_PORT:-80}"
UVICORN_PORT="${UVICORN_PORT:-8000}"

# ---------- 1. 系统环境 ----------
step "安装系统依赖..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv python3-dev \
    nginx git curl build-essential > /dev/null
log "系统依赖安装完成"

# ---------- 2. 创建应用用户（非 root 时） ----------
if [ "$APP_USER" != "root" ] && ! id -u "$APP_USER" &>/dev/null; then
    step "创建应用用户 $APP_USER ..."
    useradd -r -s /bin/bash -d "$APP_DIR" -m "$APP_USER"
fi

# ---------- 3. 配置 .env ----------
if [ ! -f "$APP_DIR/.env" ]; then
    step "创建 .env 配置文件..."
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
    sed -i "s/^JWT_SECRET=.*/JWT_SECRET=$JWT_SECRET/" "$APP_DIR/.env"
    warn "请编辑 $APP_DIR/.env 填入 DashScope API Key:"
    warn "  nano $APP_DIR/.env"
else
    log ".env 已存在，跳过"
fi

# ---------- 4. Python 虚拟环境 ----------
step "创建 Python 虚拟环境..."
if [ ! -d "$APP_DIR/.venv" ]; then
    python3 -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/pip" install -q --upgrade pip
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
log "Python 依赖安装完成"

# ---------- 5. 创建必要目录 ----------
step "创建运行时目录..."
mkdir -p "$APP_DIR/data/documents" "$APP_DIR/data/chroma" "$APP_DIR/logs"
chown -R "$APP_USER:$APP_USER" "$APP_DIR" 2>/dev/null || true

# ---------- 6. systemd 服务 ----------
step "配置 systemd 服务..."
cat > /etc/systemd/system/seckb.service << EOF
[Unit]
Description=SecKB 企业网络安全助手
After=network.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/uvicorn app.backend.main:app --host 127.0.0.1 --port $UVICORN_PORT
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable seckb
systemctl restart seckb
log "systemd 服务已启动"

# ---------- 7. Nginx 反向代理 ----------
step "配置 Nginx 反向代理..."
[ "$DOMAIN" = "_" ] && SERVER_NAME="_" || SERVER_NAME="$DOMAIN"

cat > /etc/nginx/sites-available/seckb << EOF
server {
    listen $NGINX_PORT;
    server_name $SERVER_NAME;
    client_max_body_size 100M;

    location / {
        proxy_pass http://127.0.0.1:$UVICORN_PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
    }
}
EOF

ln -sf /etc/nginx/sites-available/seckb /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
log "Nginx 配置完成"

# ---------- 8. 防火墙 ----------
step "配置防火墙..."
if command -v ufw &>/dev/null && ufw status | grep -q active; then
    ufw allow "$NGINX_PORT/tcp" 2>/dev/null || true
    log "防火墙已放行 $NGINX_PORT"
fi

# ---------- 完成 ----------
SERVER_IP=$(curl -s4 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  SecKB 部署完成！${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "  访问地址:  http://$SERVER_IP"
echo "  项目目录:  $APP_DIR"
echo ""
echo "  管理命令:"
echo "    systemctl status seckb    查看状态"
echo "    systemctl restart seckb   重启服务"
echo "    journalctl -u seckb -f    实时日志"
echo ""
