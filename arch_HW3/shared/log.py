import json
import threading
from datetime import datetime, timezone

_lock = threading.Lock()


def event(name, **fields):
    with _lock:
        print(
            json.dumps(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "event": name,
                    **fields,
                },
                default=str,
                ensure_ascii=False,
            ),
            flush=True,
        )
