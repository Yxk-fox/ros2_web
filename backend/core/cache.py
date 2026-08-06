#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单 LRU 内存缓存模块
"""

import time
from collections import OrderedDict


class SimpleCache:
    def __init__(self, maxsize=128):
        self._cache = OrderedDict()
        self._maxsize = maxsize

    def get(self, key):
        if key in self._cache:
            self._cache.move_to_end(key)
            value, expire_at = self._cache[key]
            if expire_at and time.time() > expire_at:
                del self._cache[key]
                return None
            return value
        return None

    def set(self, key, value, ttl=60):
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = (value, time.time() + ttl if ttl else None)
        while len(self._cache) > self._maxsize:
            self._cache.popitem(last=False)

    def invalidate(self, prefix=None):
        if prefix is None:
            self._cache.clear()
        else:
            keys_to_delete = [k for k in self._cache if k.startswith(prefix)]
            for k in keys_to_delete:
                del self._cache[k]

_memory_cache = SimpleCache(maxsize=256)


# ============================================================
# 端口占用检测
# ============================================================
