"""Check platform.db tenant toggles for CyCraft connector."""

from __future__ import annotations

from app.config import get_platform_settings
from app.platform.store import PlatformStore


def any_tenant_cycraft_enabled() -> bool:
    """Return True if at least one tenant has CyCraft enabled in platform.db."""
    ps = get_platform_settings()
    if not ps.platform_enabled:
        return False
    store = PlatformStore(ps.db_path_resolved())
    store.init()
    return store.count_cycraft_enabled_tenants() > 0
