"""Minimal lifecycle-safe authority resolution for v0.6 read surfaces.

This module intentionally does not implement CompiledWorkspace, revision
families, fork/cycle diagnostics, visibility, or quarantine.  It only closes
the Phase 0A invariant: a ``supersedes`` relation can affect serving when its
source is active and its target resolves uniquely and exactly.
"""

from __future__ import annotations

from typing import List, Optional, Set

from memdsl.model import Declaration, Workspace


def resolve_unique_reference(
    workspace: Workspace,
    reference: str,
) -> Optional[Declaration]:
    """Resolve one full id or uniquely named bare reference.

    Full ids never fall back to their bare suffix.  Bare references resolve
    only when exactly one source declaration has that name.  Ambiguous,
    duplicate, empty, and wrongly prefixed references therefore have no
    authority effect in Phase 0A.
    """
    if not isinstance(reference, str) or not reference:
        return None
    if ":" in reference:
        matches = [
            declaration for declaration in workspace.declarations
            if declaration.id == reference
        ]
    else:
        matches = [
            declaration for declaration in workspace.declarations
            if declaration.name == reference
        ]
    if len(matches) != 1:
        return None
    return matches[0]


def authoritative_superseded_ids(workspace: Workspace) -> Set[str]:
    """Return full ids excluded by authoritative ``supersedes`` relations."""
    superseded: Set[str] = set()
    for source in workspace.active():
        if source.status != "active":
            continue
        for reference in source.relations().get("supersedes", []):
            target = resolve_unique_reference(workspace, reference)
            if target is not None:
                superseded.add(target.id)
    return superseded


def current_declarations(workspace: Workspace) -> List[Declaration]:
    """Return the shared v0.6 service set after safe supersede exclusion.

    This is a narrow compatibility helper, not the proposed ResolvedView.
    ``Workspace.active()`` retains its historical serviceable/non-excluded
    meaning for callers that need the unprojected source set.
    """
    superseded = authoritative_superseded_ids(workspace)
    return [
        declaration for declaration in workspace.active()
        if declaration.id not in superseded
    ]
