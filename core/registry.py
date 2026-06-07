"""Platform plug-in registry - Auto scan platforms/ Directory loading plugin"""
import importlib
import pkgutil
from typing import Dict, Type
from .base_platform import BasePlatform

_registry: Dict[str, Type[BasePlatform]] = {}
_DISABLED_PLATFORMS = {"trae", "qwen"}


def is_platform_enabled(name: str) -> bool:
    return str(name or "").strip().lower() not in _DISABLED_PLATFORMS


def register(cls: Type[BasePlatform]):
    """Decorator: Register platform plugin"""
    if not is_platform_enabled(cls.name):
        return cls
    _registry[cls.name] = cls
    return cls


def load_all():
    """Automatically scan and load platforms/ Download all plugins"""
    import platforms
    for finder, name, _ in pkgutil.iter_modules(platforms.__path__, platforms.__name__ + "."):
        platform_name = name.rsplit(".", 1)[-1].lower()
        if not is_platform_enabled(platform_name):
            continue
        try:
            importlib.import_module(f"{name}.plugin")
        except ModuleNotFoundError:
            pass


def get(name: str) -> Type[BasePlatform]:
    if not is_platform_enabled(name):
        raise KeyError(f"platform '{name}' Offline")

    # Hot-reload platform modules if they are already loaded
    import sys
    import importlib

    core_module = f"platforms.{name}.core"
    if core_module in sys.modules:
        try:
            importlib.reload(sys.modules[core_module])
            print(f"[Registry] Hot-reloaded: {core_module}")
        except Exception as e:
            print(f"[Registry] Failed to hot-reload {core_module}: {e}")

    plugin_module = f"platforms.{name}.plugin"
    if plugin_module in sys.modules:
        try:
            importlib.reload(sys.modules[plugin_module])
            print(f"[Registry] Hot-reloaded: {plugin_module}")
        except Exception as e:
            print(f"[Registry] Failed to hot-reload {plugin_module}: {e}")

    if name not in _registry:
        raise KeyError(f"platform '{name}' Not registered, registered: {list(_registry.keys())}")
    return _registry[name]


def list_platforms() -> list:
    return [
        {"name": cls.name, "display_name": cls.display_name, "version": cls.version}
        for cls in _registry.values()
        if is_platform_enabled(cls.name)
    ]
