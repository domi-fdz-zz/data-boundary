"""Data Boundary.

The current product is a local-first preliminary data-use review tool for U.S.
privacy and data-use restrictions. It combines model-assisted fact extraction,
user confirmation, deterministic assessment logic, and source-backed report
explanation.

Core principle: structured rules and reviewed source logic produce the
assessment; model calls assist fact extraction, narration, source discovery, and
report-grounded follow-up.
"""
from __future__ import annotations

from importlib.resources import files

CORE_VERSION = "0.1.0-alpha.1"
RULE_ENGINE_VERSION = "0.1.0-alpha.1"

# Resource lookups for packaged UI assets.
PKG_DATA = files(__name__) / "data"

# Local web port for the desktop / serve commands.
LOCAL_WEB_PORT = 7788
