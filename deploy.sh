#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# SecKB 一键部署脚本
# 适用系统: Ubuntu 22.04 / 24.04 LTS
# 使用方式: chmod +x deploy.sh && sudo ./deploy.sh
# ============================================================

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn() { echo -e "${RED}[WARN]${NC}  $*"; }
step() { echo -e "${CYAN}[STEP]${NC} $*"; }

# ---------- 配置（按需修改） ----------
APP_USER="${APP_USER:-seckb}"
APP_DIR="${APP_DIR:-/opt/seckb}"
DOMAIN="${DOMAIN:-_}"              # 改为你的域名，留空用 IP
NGINX_PORT="${NGINX_PORT:-80}"
UVICORN_PORT="${UVICORN_PORT:-8000}"
GIT_REPO="${GIT_REPO:-https://github.com/shihuizhang-dazhi/rag}"
# 设为空字符串则从当前目录直接复制，不从 git 拉取
# 用法: LOCAL_SRC=/home/ubuntu/workspace sudo ./deploy.sh
LOCAL_SRC="${LOCAL_SRC:-}"

# ---------- 1. 系统环境 ----------
step "更新系统并安装依赖..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv python3-dev \
    nginx git curl build-essential > /dev/null
log "系统依赖安装完成"

# ---------- 2. 创建应用用户 ----------
if ! id -u "$APP_USER" &>/dev/null; then
    step "创建应用用户 $APP_USER ..."
    useradd -r -s /bin/bash -d "$APP_DIR" -m "$APP_USER"
fi

# ---------- 3. 拉取代码 ----------
if [ -n "$LOCAL_SRC" ]; then
    step "从本地 $LOCAL_SRC 复制项目..."
    rm -rf "$APP_DIR"
    cp -a "$LOCAL_SRC" "$APP_DIR"
elif [ -d "$APP_DIR/.git" ]; then
    step "更新已有代码..."
    git -C "$APP_DIR" pull --ff-only
elif [ -d "$APP_DIR" ]; then
    step "目录已存在但不是 git 仓库，备份后重新克隆..."
    mv "$APP_DIR" "${APP_DIR}.bak.$(date +%s)"
    git clone --depth 1 "$GIT_REPO" "$APP_DIR"
else
    step "克隆项目到 $APP_DIR ..."
    git clone --depth 1 "$GIT_REPO" "$APP_DIR"
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# ---------- 4. 配置 .env ----------
if [ ! -f "$APP_DIR/.env" ]; then
    step "创建 .env 配置文件..."
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"

    # 生成随机 JWT 密钥
    JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
    sed -i "s/^# JWT_SECRET.*/JWT_SECRET=$JWT_SECRET/" "$APP_DIR/.env"

    warn "============================================"
    warn "请编辑 $APP_DIR/.env 填入你的 DashScope API Key："
    warn "  nano $APP_DIR/.env"
    warn "  (把 OPENAI_API_KEY=sk-xxx 改成真实 Key)"
    warn "============================================"
else
    log ".env 已存在，跳过"
fi

# ---------- 5. Python 虚拟环境 ----------
step "创建 Python 虚拟环境..."
if [ ! -d "$APP_DIR/.venv" ]; then
    python3 -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/pip" install -q --upgrade pip
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
log "Python 依赖安装完成"

# ---------- 6. 创建必要目录 ----------
step "创建运行时目录..."
mkdir -p "$APP_DIR/data/documents" "$APP_DIR/data/chroma" "$APP_DIR/logs"
chown -R "$APP_USER:$APP_USER" "$APP_DIR/data" "$APP_DIR/logs"

# ---------- 7. systemd 服务 ----------
step "配置 systemd 服务..."
cat > /etc/systemd/system/seckb.service << EOF
[Unit]
Description=SecKB 企业网络安全助手
After=network.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
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

# ---------- 8. Nginx 反向代理 ----------
step "配置 Nginx 反向代理..."
if [ "$DOMAIN" = "_" ]; then
    SERVER_NAME="_"
else
    SERVER_NAME="$DOMAIN"
fi

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

        # SSE 长连接支持
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

# ---------- 9. 防火墙 ----------
step "配置防火墙..."
if command -v ufw &>/dev/null && ufw status | grep -q active; then
    ufw allow "$NGINX_PORT/tcp" 2>/dev/null || true
    log "防火墙已放行 $NGINX_PORT 端口"
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
echo "  配置文件:  $APP_DIR/.env"
echo ""
echo "  管理命令:"
echo "    systemctl status seckb    查看服务状态"
echo "    systemctl restart seckb   重启服务"
echo "    journalctl -u seckb -f    查看实时日志"
echo ""
echo -e "${CYAN}  下一步：编辑 .env 填入 DashScope API Key${NC}"
echo -e "${CYAN}    nano $APP_DIR/.env${NC}"
echo -e "${CYAN}    systemctl restart seckb${NC}"
echo ""
