"""Shared Redis client with connection pool.

Replaces inline `redis.from_url()` calls so connections are pooled per-process
instead of opened/closed on every request or task tick.
"""
import redis
from app.core.config import settings

_pool = redis.ConnectionPool.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    max_connections=50,
)


def get_redis_client() -> redis.Redis:
    return redis.Redis(connection_pool=_pool)
