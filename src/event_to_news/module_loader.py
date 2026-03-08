"""
Dynamic module loader.

Discovers module classes by name from the `event_to_news.modules` package.
The module name in config.yml must match the Python file name (without .py).
The file must contain exactly one class that inherits from BaseModule.
"""

from __future__ import annotations

import importlib
import inspect
import logging
from pathlib import Path
from typing import Any, Type

from .base_module import BaseModule

logger = logging.getLogger(__name__)

_cache: dict[str, Type[BaseModule]] = {}


def load_module_class(module_name: str) -> Type[BaseModule]:
    """
    Resolve a module name (e.g. "pronote") to its BaseModule subclass.

    Looks in `event_to_news.modules.<module_name>`.
    Results are cached so the import only happens once.
    """
    if module_name in _cache:
        return _cache[module_name]

    full_name = f"event_to_news.modules.{module_name}"
    try:
        mod = importlib.import_module(full_name)
    except ModuleNotFoundError as exc:
        raise ImportError(
            f"Module '{module_name}' not found. "
            f"Expected a file at src/event_to_news/modules/{module_name}.py"
        ) from exc

    # Find the first concrete BaseModule subclass defined in this file
    candidates = [
        obj
        for _, obj in inspect.getmembers(mod, inspect.isclass)
        if issubclass(obj, BaseModule)
        and obj is not BaseModule
        and not inspect.isabstract(obj)
        and obj.__module__ == full_name
    ]

    if not candidates:
        raise ImportError(
            f"No concrete BaseModule subclass found in {full_name}. "
            "Make sure your module defines a class that inherits from BaseModule."
        )

    if len(candidates) > 1:
        logger.warning(
            "Multiple BaseModule subclasses found in %s: %s — using %s",
            full_name,
            [c.__name__ for c in candidates],
            candidates[0].__name__,
        )

    _cache[module_name] = candidates[0]
    return candidates[0]


def instantiate_module(
    module_name: str, feed_slug: str, params: dict[str, Any], data_dir: Path
) -> BaseModule:
    """Load and instantiate a module by name, passing its private data directory."""
    cls = load_module_class(module_name)
    return cls(feed_slug=feed_slug, params=params, data_dir=data_dir)
