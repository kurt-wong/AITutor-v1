# AI Tutor — 升级指南

> 从 v1.x 升级到更高版本的标准操作流程。

---

## 升级接口

AI Tutor 通过以下标准接口支持版本升级：

### 1. 数据库迁移 (Alembic)

所有数据库变更通过 Alembic 迁移脚本管理。

```bash
# 在 NAS 上执行
docker exec aitutor-backend alembic upgrade head
```

升级前建议备份数据库：
```bash
docker exec aitutor-postgres pg_dump -U postgres ai_tutor > backup_$(date +%Y%m%d).sql
```

### 2. API 版本化

API 端点统一挂载在 `/api/` 前缀下。
当引入破坏性变更时，新版本端点使用 `/api/v2/` 前缀，
同时保留旧版本至少一个发布周期。

### 3. 配置迁移

运行时配置存储在 `system_configs` 表中。
新增配置项通过 Alembic 迁移 seed 默认值。
现有配置项不会被覆盖。

### 4. Docker 镜像升级

```bash
# 1. 拉取/加载新镜像
docker load < aitutor-v1.1.0.tar.gz

# 2. 更新 docker-compose.prod.yml 中的镜像标签
#    将 aitutor-backend:v1.0.0 改为 aitutor-backend:v1.1.0

# 3. 停止旧版本
docker compose -f docker-compose.prod.yml down

# 4. 启动新版本
docker compose -f docker-compose.prod.yml up -d

# 5. 运行数据库迁移
docker exec aitutor-backend alembic upgrade head
```

### 5. 数据卷持久化

以下 Docker volumes 在升级过程中保持不变，无需重新创建：
- `pgdata` — PostgreSQL 数据
- `redisdata` — Redis 数据
- `miniodata` — MinIO 对象存储

---

## 升级检查清单

- [ ] 已备份数据库 (`pg_dump`)
- [ ] 已阅读新版本的 CHANGELOG
- [ ] 已更新 `.env.production` 中的新环境变量
- [ ] 已更新 Docker 镜像
- [ ] 已运行 `alembic upgrade head`
- [ ] 已验证前端可访问
- [ ] 已验证 API 可访问 (`/docs`)
- [ ] 已验证 LLM 连接 (Settings → 测试连接)

---

## 回滚

如果升级失败：

```bash
# 1. 切回旧版本镜像标签
# 2. 还原数据库备份
docker exec -i aitutor-postgres psql -U postgres ai_tutor < backup_YYYYMMDD.sql
# 3. 重启服务
docker compose -f docker-compose.prod.yml up -d
```
