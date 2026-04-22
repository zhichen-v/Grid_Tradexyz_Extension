"""
Core package exports.

Keep top-level imports lazy so importing `core.*` submodules does not
eagerly initialize unrelated services such as DI or event handling.
"""

from importlib import import_module
from typing import Any

__version__ = "2.0.0"
__author__ = "Trading System Team"

_LAZY_EXPORTS = {
    "get_container": ("core.di.container", "get_container"),
    "DIContainer": ("core.di.container", "DIContainer"),
    "IService": ("core.services.interfaces.base", "IService"),
    "BaseService": ("core.services.interfaces.base", "BaseService"),
    "MonitoringService": (
        "core.services.interfaces.monitoring_service",
        "MonitoringService",
    ),
}


def __getattr__(name: str) -> Any:
    """Lazily load top-level exports to avoid package import side effects."""
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'core' has no attribute '{name}'")

    module_name, attr_name = _LAZY_EXPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


__all__ = [
    "get_container",
    "DIContainer",
    "IService",
    "BaseService",
    "MonitoringService",
]
