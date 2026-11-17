from __future__ import annotations

import pkgutil


def discover_modules() -> list[str]:
    return sorted(
        f".{module.name}"
        for module in pkgutil.iter_modules(__path__)
        if not module.name.startswith("_")
    )

ALL_MODULES = discover_modules()
__all__ = ["ALL_MODULES", "discover_modules"]
