import threading
import time
from functools import wraps
from typing import Any, Callable


class CacheEntry:
    def __init__(self, value: Any, expires_at: float):
        self.value = value
        self.expires_at = expires_at

class MemoryCache:
    def __init__(self):
        self._cache = {}
        self._lock = threading.RLock()

    def get(self, key):
        now = time.time()
        with self._lock:
            entry = self._cache.get(key)
            if entry and entry.expires_at > now:
                return entry.value
            if entry:
                del self._cache[key]
        return None

    def set(self, key, value, ttl):
        expires_at = time.time() + ttl
        with self._lock:
            self._cache[key] = CacheEntry(value, expires_at)

    def clear(self):
        with self._lock:
            self._cache.clear()

cache = MemoryCache()

def make_cache_key(func: Callable, *args, **kwargs):
    # Support Flask request context param cache: get query string for GET, or JSON for POST
    key_parts = [func.__name__]
    if hasattr(args[0], 'args') and hasattr(args[0], 'method'):
        req = args[0]
        if req.method == 'GET':
            key_parts.append(str(sorted(req.args.items())))
        elif req.method == 'POST':
            try:
                key_parts.append(str(sorted(req.get_json().items())))
            except Exception:
                pass
    else:
        key_parts += [str(a) for a in args[1:]]
        key_parts += [f'{k}={repr(v)}' for k,v in sorted(kwargs.items())]
    return '|'.join(key_parts)

def cached(ttl=60):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            from flask import request
            key = make_cache_key(f, request)
            value = cache.get(key)
            if value is not None:
                return value
            result = f(*args, **kwargs)
            cache.set(key, result, ttl)
            return result
        return wrapper
    return decorator
