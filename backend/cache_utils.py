"""
cache_utils.py

A tiny in-memory TTL cache decorator for expensive backend operations --
Hopsworks feature-store reads, model downloads, SHAP explanations, etc.
FastAPI has no built-in equivalent to Streamlit's @st.cache_data/
@st.cache_resource, so this recreates the same idea: cache a function's
result for N seconds, so repeated calls within that window skip the real
work entirely.

Usage:
    from cache_utils import ttl_cache

    @ttl_cache(ttl_seconds=300)  # 5 min
    def fetch_hourly_dataset(fs):
        ...  # the slow Hopsworks call

Calling `fetch_hourly_dataset.cache_clear()` wipes that function's cache --
wire this to your Refresh endpoint (see main_py_cache_wiring.py) so a
manual refresh actually bypasses the cache instead of just returning the
same stale result.

CAVEAT: this is a single-process in-memory cache. Fine for one backend
instance (Render/Railway/Fly free-to-small tiers all run one instance by
default). If you ever scale to multiple instances behind a load balancer,
each instance would have its own separate cache -- at that point you'd
want a shared cache like Redis instead. Not a concern until then.
"""

import functools
import time


def ttl_cache(ttl_seconds: int = 300):
    def decorator(func):
        cache: dict = {}

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.time()

            if key in cache:
                value, cached_at = cache[key]
                if now - cached_at < ttl_seconds:
                    return value

            result = func(*args, **kwargs)
            cache[key] = (result, now)
            return result

        def cache_clear():
            cache.clear()

        wrapper.cache_clear = cache_clear
        return wrapper

    return decorator