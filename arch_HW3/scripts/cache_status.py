import json
from services.flight.cache import Cache

cache = Cache()
print("Sentinel master:", cache.sentinel.discover_master("flights"))
for pattern in ("flight:*", "search:*"):
    for index, key in enumerate(cache.redis.scan_iter(pattern)):
        if index >= 20:
            break
        print(json.dumps({"key": key.decode(), "ttl": cache.redis.ttl(key)}))
