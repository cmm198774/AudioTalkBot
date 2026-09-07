# Docker 部署指南

本项目已配置 Docker 支持，可以方便地部署到任何支持 Docker 的服务器上。

## 前置要求

- Docker Engine 19.03+
- Docker Compose 1.27+

## 快速开始

### 1. 准备 .env 文件

确保项目根目录有 `.env` 文件，参考 `.env.example`：

```bash
cp .env.example .env
```

编辑 `.env` 文件，配置你的 API 密钥（注意：用户现在可以在界面上自己配置 API Key，这里不需要配置 DASHSCOPE_API_KEY）。

### 2. 构建镜像

```bash
docker-compose build
```

或只使用 Docker：

```bash
docker build -t voice-chatbot .
```

### 3. 启动服务

使用 docker-compose（推荐）：

```bash
docker-compose up -d
```

或使用 Docker：

```bash
docker run -d \
  --name voice-chatbot \
  -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/.env:/app/.env:ro \
  --restart unless-stopped \
  voice-chatbot
```

### 4. 访问服务

服务启动后，访问：http://localhost:8000

## 数据持久化

- **用户数据**：`./data` 目录会被挂载到容器的 `/app/data`，包括：
  - `users.json` - 用户账号信息
  - `sessions/{username}/` - 每个用户的会话和预设

- **环境变量**：`.env` 文件以只读方式挂载

## 常用命令

### 查看日志

```bash
docker-compose logs -f
```

或：

```bash
docker logs -f voice-chatbot
```

### 停止服务

```bash
docker-compose down
```

或：

```bash
docker stop voice-chatbot
docker rm voice-chatbot
```

### 重启服务

```bash
docker-compose restart
```

或：

```bash
docker restart voice-chatbot
```

### 更新代码

```bash
# 拉取最新代码
git pull

# 重新构建镜像
docker-compose build

# 重启服务
docker-compose up -d
```

## 开发模式

如果需要开发时自动重载，取消 `docker-compose.yml` 中 `command` 行的注释：

```yaml
command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

然后重启容器：

```bash
docker-compose restart
```

## 注意事项

1. **端口冲突**：如果 8000 端口被占用，可以修改 `docker-compose.yml` 中的端口映射，例如改为 `8080:8000`

2. **权限问题**：确保 `data` 目录有写入权限

3. **备份数据**：定期备份 `data` 目录，包含所有用户数据

4. **HTTPS**：生产环境建议使用反向代理（如 Nginx）配置 HTTPS

## 部署到服务器

以阿里云为例：

1. 安装 Docker：
```bash
curl -fsSL https://get.docker.com | bash
```

2. 安装 Docker Compose：
```bash
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose
```

3. 上传代码到服务器：
```bash
git clone <your-repo-url>
cd AudioTalkBot
```

4. 配置 .env 文件并启动服务

## 故障排查

### 容器无法启动

查看日志：
```bash
docker-compose logs
```

常见问题：
- 端口被占用：修改端口映射
- .env 文件不存在：创建 .env 文件
- data 目录权限：`chmod 777 data`

### 数据丢失

确保 `data` 目录正确挂载：
```bash
docker-compose exec voice-chatbot ls -la /app/data
```

## 性能优化

生产环境建议：

1. 使用多阶段构建减小镜像体积
2. 配置 Nginx 反向代理和负载均衡
3. 使用 Redis 缓存 session（需要修改代码）
4. 配置日志轮转
5. 使用 Supervisor 管理进程

## 安全建议

1. 不要将 .env 文件提交到 Git
2. 定期更新依赖版本
3. 使用非 root 用户运行容器（需要修改 Dockerfile）
4. 配置防火墙规则
5. 启用 HTTPS
