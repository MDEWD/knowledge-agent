# Tailscale 接入（免域名 · 免公网 IP · 自动 HTTPS）

> 适用场景：自己 + 少量家人设备访问，不想买域名、不想开公网端口、不想备案。
> 前置条件：能安装 Tailscale 的机器（Linux 服务器 / NAS / 家里的常开电脑均可）。

## 一、原理

Tailscale 基于 WireGuard 建立点对点加密虚拟网络（tailnet）。每台设备加入后获得：

- 一个 tailnet 内网 IP（`100.x.x.x`）
- 一个免费的 MagicDNS 域名（`机器名.xxx.ts.net`）
- 自动签发的 HTTPS 证书（Tailscale 官方 CA）

于是 Caddy 原本「买域名 → 公网 IP → Let's Encrypt 签证书」的整条链路，全部由 Tailscale 免费替代。

本项目采用 **方案 A（推荐）**：用 `tailscale serve` 直接反代到 app 的 `127.0.0.1:8000`，Caddy 暂不参与。

---

## 二、前置检查

1. 在 Tailscale 管理后台（https://login.tailscale.com/admin/dns）确认：
   - **MagicDNS** 已开启（默认开启）
   - **HTTPS Certificates** 已开启（默认开启）
2. 本机 Docker 环境已装好，`docker compose up -d` 能正常启动项目。
3. 确认 `docker-compose.yml` 里 app 端口绑定为 `127.0.0.1:8000`（本项目已如此，无需改动）。

---

## 三、方案 A（推荐）：tailscale serve 直连

### 1. 在服务器上安装 Tailscale

```bash
# Linux（Debian/Ubuntu/CentOS 通用）
curl -fsSL https://tailscale.com/install.sh | sh
```

### 2. 登录并启动

```bash
sudo tailscale up
```

终端会打印一个 `https://login.tailscale.com/a/xxxx` 链接，浏览器打开并登录你的账号完成授权。

### 3. 查看机器域名

```bash
tailscale status
```

输出第一行类似：

```text
100.101.102.103  myserver  user@example.com  linux   -
```

你的访问域名就是 `myserver.<tailnet名>.ts.net`（`tailnet名` 是登录账号自带的后缀，`tailscale status` 里能看到完整 `*.ts.net`）。

### 4. 启动项目（只起 db + app，不需要 caddy）

```bash
docker compose up -d db app
```

### 5. 开启 serve，把 app 端口暴露到 tailnet 的 443

```bash
tailscale serve --bg 8000
```

等价于 `tailscale serve --bg --https=443 http://127.0.0.1:8000`，Tailscale 会自动签发并续期 HTTPS 证书。

查看配置：`tailscale serve status`
清除配置：`tailscale serve reset`

### 6. 客户端访问

在手机 / 笔记本上安装 Tailscale App，登录**同一个账号**，然后直接浏览器打开：

```text
https://myserver.<tailnet名>.ts.net
```

即可访问知研 Agent，全程 HTTPS，无需公网 IP、无需开防火墙端口。

### 7. 环境变量调整

HTTPS 已就绪，把根目录 `.env` 里的安全项改到位：

```env
AUTH_COOKIE_SECURE=true
AUTH_EXPOSE_CODES=false
CORS_ORIGINS=          # 同源部署留空即可
DOMAIN=myserver.<tailnet名>.ts.net
```

重启生效：

```bash
docker compose up -d db app
```

---

## 四、方案 B（可选）：保留 Caddy + Tailscale 证书

适合想保留现有 Caddyfile（SSE `flush_interval -1` 等配置）的人。代价是证书需要手动续期。

### 1. 签发证书

```bash
mkdir -p ~/ts-certs && cd ~/ts-certs
sudo tailscale cert myserver.<tailnet名>.ts.net
# 生成 myserver.<tailnet名>.ts.net.crt 和 .key
```

### 2. 修改 Caddyfile

```caddy
myserver.<tailnet名>.ts.net {
	encode gzip
	tls /etc/caddy/certs/myserver.<tailnet名>.ts.net.crt /etc/caddy/certs/myserver.<tailnet名>.ts.net.key
	reverse_proxy app:8000 {
		flush_interval -1
	}
}
```

### 3. 挂载证书并重启

在 `docker-compose.yml` 的 `caddy` 服务加一卷：

```yaml
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - ./ts-certs:/etc/caddy/certs:ro
```

根目录 `.env` 设 `DOMAIN=myserver.<tailnet名>.ts.net`，然后 `docker compose up -d`。

### 4. 证书自动续期（cron）

Tailscale 证书有有效期，需定期续期并让 Caddy 重载：

```bash
sudo crontab -e
# 每天凌晨 3 点续期并重载 Caddy
0 3 * * * cd /root/ts-certs && /usr/bin/tailscale cert myserver.<tailnet名>.ts.net && cd /path/to/zhiyan-agent && docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile
```

> 嫌麻烦就选方案 A，证书全自动，不用管。

---

## 五、注意事项

1. **客户端必须登录同一个 Tailscale 账号**，否则访问不到（tailnet 是私有的）。
2. `tailscale serve` 只对 tailnet 内可见，**不会暴露到公网**——这正是「先内部用、以后再公开」想要的隔离效果。
3. 若以后要公开分享：买域名 + 服务器公网 IP，DNS 指向服务器，把 `DOMAIN` 换成真实域名、恢复原 Caddyfile（去掉 `tls` 证书行，让 Caddy 走 Let's Encrypt），`docker compose up -d` 即可平滑切换。
4. 家里电脑做主机需要保持开机、且注意运营商网络（部分宽带无公网 IP，但 Tailscale 可 NAT 穿透，一般无碍）。
