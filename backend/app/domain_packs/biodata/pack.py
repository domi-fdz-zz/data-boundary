"""
BioData / GEO / DEA pack.

Fully config-driven: config.json (routing + field_map + missing-info specs),
rules.json (the 5 rules), evidence_fixtures.json (the 4 citations). No bespoke
Python behaviour is needed, so we just instantiate ConfigDrivenPack over this
folder.
"""
from __future__ import annotations

from pathlib import Path

from ..base import ConfigDrivenPack, DomainPack


def get_pack() -> DomainPack:
    return ConfigDrivenPack(Path(__file__).parent)
