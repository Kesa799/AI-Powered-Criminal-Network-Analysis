"""Tell model-derived mentions from locally extracted ones.

The backend can supplement a document with the output of its local
regex/NER extractor when the model produced no usable mentions. Such a
mention must never be presented as if the model had produced it, so both the
bulk ingest script and the cleanup script need the same way of telling the
two apart.

The distinction is made on the mention *role*: the local extractor assigns a
fixed set of roles (and only the local extractor assigns them), while a
model-derived mention carries the role the model stated.
"""

from __future__ import annotations

from typing import Optional, Set

import requests

# Roles that only the backend's local regex/NER extractor assigns.
REGEX_ROLES: Set[str] = {
    "Subscriber",
    "Hardware Device",
    "Suspect Vehicle",
    "Bank Account",
    "Cell Tower CGI",
    "Accused / Suspect",
}

# Role prefixes that only the local extractor assigns.
REGEX_ROLE_PREFIXES = ("Accused (", "Accused /")


def is_regex_role(role: Optional[str]) -> bool:
    """True when the role can only have been produced by the local extractor."""
    text = str(role or "")
    return text in REGEX_ROLES or text.startswith(REGEX_ROLE_PREFIXES)


def has_model_derived_mentions(
    session: requests.Session,
    base_url: str,
    evidence_id: Optional[str],
) -> Optional[bool]:
    """Whether an evidence row holds at least one model-derived mention.

    Returns None when the mentions cannot be read, so a caller can treat an
    unknown answer as "leave this row alone" rather than deleting good data.
    """
    if not evidence_id:
        return None
    try:
        r = session.get(
            f"{base_url}/api/evidence/{evidence_id}/results/mentions",
            timeout=120,
        )
        r.raise_for_status()
    except Exception:
        return None
    items = r.json().get("items") or []
    if not items:
        return False
    for item in items:
        if not is_regex_role(item.get("role")):
            return True
    return False


__all__ = [
    "REGEX_ROLES",
    "REGEX_ROLE_PREFIXES",
    "has_model_derived_mentions",
    "is_regex_role",
]
