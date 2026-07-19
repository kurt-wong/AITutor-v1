"""
Redis + MinIO 真实集成测试

验证:
1. Redis 连接、读写、过期
2. MinIO 连接、上传、下载、删除
3. 应用层 Redis/MinIO 操作（非 mock）
"""

import pytest
import json
from io import BytesIO


class TestRedisIntegration:
    """Redis 真实连接测试"""

    @pytest.mark.asyncio
    async def test_redis_connection(self, redis_conn):
        pong = await redis_conn.ping()
        assert pong is True

    @pytest.mark.asyncio
    async def test_redis_set_get(self, redis_conn):
        await redis_conn.set("test:key1", "value1")
        result = await redis_conn.get("test:key1")
        assert result == "value1"

    @pytest.mark.asyncio
    async def test_redis_json(self, redis_conn):
        data = {"name": "test", "value": 123}
        await redis_conn.set("test:json", json.dumps(data))
        raw = await redis_conn.get("test:json")
        result = json.loads(raw)
        assert result["name"] == "test"

    @pytest.mark.asyncio
    async def test_redis_expire(self, redis_conn):
        await redis_conn.set("test:expire", "value", ex=10)
        ttl = await redis_conn.ttl("test:expire")
        assert ttl > 0

    @pytest.mark.asyncio
    async def test_redis_delete(self, redis_conn):
        await redis_conn.set("test:del", "value")
        await redis_conn.delete("test:del")
        result = await redis_conn.get("test:del")
        assert result is None

    @pytest.mark.asyncio
    async def test_redis_list_ops(self, redis_conn):
        await redis_conn.delete("test:list")
        await redis_conn.rpush("test:list", "a", "b", "c")
        length = await redis_conn.llen("test:list")
        assert length == 3

    @pytest.mark.asyncio
    async def test_redis_hash_ops(self, redis_conn):
        await redis_conn.delete("test:hash")
        await redis_conn.hset("test:hash", mapping={"f1": "v1", "f2": "v2"})
        result = await redis_conn.hgetall("test:hash")
        assert result["f1"] == "v1"


class TestMinIOIntegration:
    """MinIO 真实连接测试"""

    def test_minio_connection(self, minio_client):
        buckets = minio_client.list_buckets()
        bucket_names = [b.name for b in buckets]
        assert "images" in bucket_names

    def test_minio_upload_download(self, minio_client, sample_image):
        object_name = "test/upload_test.jpg"
        minio_client.put_object("images", object_name, BytesIO(sample_image), len(sample_image))
        response = minio_client.get_object("images", object_name)
        downloaded = response.read()
        response.close()
        response.release_conn()
        assert downloaded == sample_image
        minio_client.remove_object("images", object_name)

    def test_minio_delete(self, minio_client, sample_image):
        object_name = "test/delete_test.jpg"
        minio_client.put_object("images", object_name, BytesIO(sample_image), len(sample_image))
        minio_client.remove_object("images", object_name)
        try:
            minio_client.stat_object("images", object_name)
            assert False
        except Exception:
            pass

    def test_minio_list_objects(self, minio_client, sample_image):
        for i in range(3):
            minio_client.put_object("images", f"test/list_{i}.jpg", BytesIO(sample_image), len(sample_image))
        objects = minio_client.list_objects("images", prefix="test/list_", recursive=True)
        names = [obj.object_name for obj in objects]
        assert len(names) >= 3
        for name in names:
            minio_client.remove_object("images", name)


class TestAppRedisIntegration:
    """应用层 Redis 操作"""

    @pytest.mark.asyncio
    async def test_app_redis_module(self, redis_conn):
        from app.db.redis import redis_client
        await redis_client.set("test:app", "ok")
        result = await redis_client.get("test:app")
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_app_redis_helpers(self, redis_conn):
        from app.db.redis import lpush, rpush, lrange
        await lpush("test:list2", "first")
        await rpush("test:list2", "second")
        items = await lrange("test:list2", 0, -1)
        assert "first" in items


class TestAppMinIOIntegration:
    """应用层 MinIO 操作"""

    def test_app_minio_upload_download(self, sample_image):
        from app.db.minio import upload_file, download_file, delete_file
        object_name = "test/app_test.jpg"
        upload_file(object_name, BytesIO(sample_image), len(sample_image), "image/jpeg", bucket="images")
        result = download_file(object_name, bucket="images")
        assert result == sample_image
        delete_file(object_name, bucket="images")
