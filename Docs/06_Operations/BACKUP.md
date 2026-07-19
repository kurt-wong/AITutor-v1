# AI Tutor — 备份策略

> NAS (Synology DS3622xs+) 部署环境的数据备份指南。

---

## 备份内容

| 数据 | 存储位置 | 备份方式 |
|------|---------|---------|
| PostgreSQL 数据库 | Docker volume `pgdata` | `pg_dump` 定时导出 |
| MinIO 对象 (PDF/图片) | Docker volume `miniodata` | Hyper Backup 目录同步 |
| Redis 缓存 | Docker volume `redisdata` | 无需备份（缓存可重建） |
| 系统配置 | `system_configs` 表 | 随数据库一同备份 |

---

## 自动备份脚本 (NAS 任务计划)

在 NAS 控制面板 → 任务计划中添加以下脚本，建议每日凌晨 3:00 执行：

```bash
#!/bin/bash
BACKUP_DIR="/volume1/backup/aitutor"
KEEP_DAYS=30
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

# ── 1. 数据库备份 ──
docker exec aitutor-postgres pg_dump -U postgres ai_tutor \
  > "$BACKUP_DIR/aitutor_db_$DATE.sql"

# 压缩
gzip "$BACKUP_DIR/aitutor_db_$DATE.sql"

# ── 2. 清理旧备份 ──
find "$BACKUP_DIR" -name "aitutor_db_*.sql.gz" -mtime +$KEEP_DAYS -delete

echo "[$DATE] Backup completed: aitutor_db_$DATE.sql.gz"
```

## 手动备份

```bash
# 数据库
docker exec aitutor-postgres pg_dump -U postgres ai_tutor > aitutor_backup.sql

# 完整数据目录 (需要停止服务)
docker compose -f docker-compose.prod.yml down
tar -czf aitutor_data_backup.tar.gz /volume1/docker/aitutor/
docker compose -f docker-compose.prod.yml up -d
```

## 恢复

```bash
# 数据库恢复
docker exec -i aitutor-postgres psql -U postgres ai_tutor < aitutor_backup.sql

# 完整恢复
docker compose -f docker-compose.prod.yml down
tar -xzf aitutor_data_backup.tar.gz -C /
docker compose -f docker-compose.prod.yml up -d
docker exec aitutor-backend alembic upgrade head
```
