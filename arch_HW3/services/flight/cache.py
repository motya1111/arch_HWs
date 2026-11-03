import base64
import json
import os
from google.protobuf.message import DecodeError
from redis import RedisError
from redis.sentinel import Sentinel
from shared.log import event


class Cache:
    def __init__(self):
        self.ttl = int(os.getenv("CACHE_TTL_SECONDS", "300"))
        if not 300 <= self.ttl <= 600:
            raise ValueError("CACHE_TTL_SECONDS must be 300..600")
        nodes = [
            address.rsplit(":", 1)
            for address in os.getenv(
                "REDIS_SENTINELS", "sentinel-1:26379,sentinel-2:26379,sentinel-3:26379"
            ).split(",")
        ]
        self.sentinel = Sentinel(
            [(host, int(port)) for host, port in nodes],
            socket_timeout=0.25,
            socket_connect_timeout=0.25,
            sentinel_kwargs={"socket_timeout": 0.25, "socket_connect_timeout": 0.25},
        )
        self.redis = self.sentinel.master_for(
            "flights", socket_timeout=0.25, socket_connect_timeout=0.25
        )

    def read(self, key):
        try:
            value = self.redis.get(key)
            return json.loads(value) if value else None
        except (RedisError, ValueError, TypeError) as exc:
            event("cache_unavailable", operation="get", reason=type(exc).__name__)
            return None

    def resolve(self, key, cached, epoch, message_type, loader):
        if isinstance(cached, dict) and cached.get("epoch") == epoch:
            try:
                result = message_type.FromString(
                    base64.b64decode(cached["data"], validate=True)
                )
                event("cache_hit", key=key)
                return result
            except (ValueError, KeyError, TypeError, DecodeError):
                pass
        event("cache_miss", key=key)
        result = loader()
        try:
            self.redis.set(
                key,
                json.dumps(
                    {
                        "epoch": epoch,
                        "data": base64.b64encode(result.SerializeToString()).decode(),
                    }
                ),
                ex=self.ttl,
            )
        except RedisError as exc:
            event("cache_unavailable", operation="set", reason=type(exc).__name__)
        return result

    def invalidate(self, flight_id, routes):
        keys = [f"flight:{flight_id}"]
        for origin, destination, day in routes:
            keys.extend(
                [
                    f"search:{origin}:{destination}:{day}",
                    f"search:{origin}:{destination}:any",
                ]
            )
        try:
            self.redis.delete(*set(keys))
            event("cache_invalidated", keys=sorted(set(keys)))
        except RedisError as exc:
            event(
                "cache_unavailable", operation="invalidate", reason=type(exc).__name__
            )

    def healthy(self):
        try:
            return bool(self.redis.ping())
        except RedisError:
            return False
