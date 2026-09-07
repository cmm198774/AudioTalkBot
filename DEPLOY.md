# 阿里云部署指南

本文档介绍如何将语音对话机器人部署到阿里云服务器。

## 方案选择

### 推荐：ECS 或轻量应用服务器
- **配置要求**：2核4G内存，40G系统盘
- **系统**：Ubuntu 20.04/22.04 或 CentOS 7/8
- **带宽**：3-5Mbps（语音流需要）
- **预估费用**：轻量应用服务器约 100-200元/月

## 部署步骤

### 1. 购买并配置服务器

1. 登录 [阿里云控制台](https://ecs.console.aliyun.com/)
2. 创建 ECS 实例或轻量应用服务器
3. 选择 Ubuntu 22.04 或 CentOS 8
4. 配置安全组，开放以下端口：
   - **22** (SSH)
   - **8000** (应用端口)
5. 记录服务器的公网 IP 地址

### 2. 连接服务器

```bash
# SSH 连接
ssh root@<你的服务器IP>
```

### 3. 安装 Docker 和 Docker Compose

```bash
# Ubuntu
apt update
apt install -y docker.io docker-compose-v2

# 启动 Docker
systemctl start docker
systemctl enable docker

# 验证安装
docker --version
docker-compose --version
```

### 4. 部署应用

```bash
# 克隆代码
cd /opt
git clone https://github.com/cmm198774/AudioTalkBot.git
cd AudioTalkBot

# 创建数据目录
mkdir -p data

# 创建 .env 文件（用户现在可以在界面上配置 API Key，这里不需要配置）
cat > .env << EOF
# 如果需要配置全局 API Key（可选，用户可以在界面上覆盖）
# DASHSCOPE_API_KEY=your-api-key-here
EOF

# 构建并启动
docker-compose up -d --build
```

### 5. 验证部署

```bash
# 查看日志
docker-compose logs -f

# 检查容器状态
docker-compose ps

# 测试访问
curl http://localhost:8000
```

访问地址：`http://<你的服务器IP>:8000`

### 6. 配置 HTTPS（可选但推荐）

使用 Nginx 反向代理 + Let's Encrypt：

```bash
# 安装 Nginx 和 Certbot
apt install -y nginx certbot python3-certbot-nginx

# 配置 Nginx
cat > /etc/nginx/sites-available/voice-chatbot << EOF
server {
    listen 80;
    server_name your-domain.com;  # 替换为你的域名

    location / {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

# 启用配置
ln -s /etc/nginx/sites-available/voice-chatbot /etc/nginx/sites-enabled/
nginx -t
systemctl reload nginx

# 申请 SSL 证书
certbot --nginx -d your-domain.com
```

## 常用运维命令

```bash
# 查看日志
docker-compose logs -f

# 重启服务
docker-compose restart

# 停止服务
docker-compose down

# 更新代码
git pull
docker-compose up -d --build

# 查看资源使用
docker stats

# 进入容器
docker-compose exec voice-chatbot bash
```

## 数据备份

```bash
# 备份数据目录
tar -czf backup-$(date +%Y%m%d).tar.gz data/

# 恢复数据
tar -xzf backup-20260907.tar.gz
```

## 故障排查

### 容器无法启动
```bash
# 查看详细日志
docker-compose logs voice-chatbot

# 检查端口占用
netstat -tlnp | grep 8000
```

### WebSocket 连接失败
- 检查安全组是否开放 8000 端口
- 检查防火墙设置
- 如果使用 Nginx，确保 WebSocket 代理配置正确

### 性能问题
```bash
# 查看容器资源使用
docker stats

# 查看系统资源
top
htop
```

## 成本优化

1. **使用抢占式实例**：费用可降低 60-90%
2. **预留实例券**：长期使用更划算
3. **监控告警**：设置 CPU/内存告警，避免资源浪费

## 安全建议

1. 修改 SSH 默认端口（22 → 其他）
2. 使用密钥登录，禁用密码登录
3. 配置 fail2ban 防止暴力破解
4. 定期更新系统补丁
5. 限制 API 访问频率（可在应用层实现）

## 监控建议

```bash
# 安装 simple-docker-monitor
# 或配置阿里云云监控

# 简单的健康检查脚本
cat > /opt/health-check.sh << 'EOF'
#!/bin/bash
if ! docker-compose -f /opt/AudioTalkBot/docker-compose.yml ps | grep -q "Up"; then
    echo "Service is down, restarting..."
    cd /opt/AudioTalkBot && docker-compose restart
fi
EOF

chmod +x /opt/health-check.sh

# 添加到 crontab
(crontab -l 2>/dev/null; echo "*/5 * * * * /opt/health-check.sh") | crontab -
```

## 注意事项

1. **WebSocket 支持**：确保 Nginx 配置正确设置了 Upgrade 和 Connection 头
2. **数据持久化**：data 目录必须挂载，否则容器重启后数据丢失
3. **API Key 安全**：每个用户可以配置自己的 API Key，不要在代码中硬编码
4. **备份策略**：建议每天自动备份 data 目录
5. **日志管理**：定期清理日志，避免磁盘满

## 性能调优

```bash
# 调整 Docker 资源限制
# 编辑 docker-compose.yml，添加：
deploy:
  resources:
    limits:
      cpus: '1.0'
      memory: 1G
    reservations:
      cpus: '0.5'
      memory: 512M
```

## 扩展建议

如果用户量增加：
1. 使用 Redis 替代 JSON 文件存储 session
2. 使用数据库存储用户数据
3. 使用负载均衡分发请求
4. 使用 CDN 加速静态资源
5. 考虑使用阿里云的函数计算（FC）或容器服务（ACK）
