"""Minimal lifecycle-safe authority resolution for v0.6 read surfaces.

Phase 0B delegates lookup to the internal CompiledWorkspace resolver while
preserving the narrow Phase 0A invariant: a ``supersedes`` relation can affect
serving when its source is active and its target resolves uniquely and exactly.
Revision families, fork/cycle diagnostics, visibility, and quarantine remain
outside this compatibility helper.
"""

from __future__ import annotations

from typing import List, Optional, Set

from memdsl.compiler import WorkspaceInput, ensure_compiled
from memdsl.model import Declaration, EXCLUDED_STATUSES


def resolve_unique_reference(
    workspace: WorkspaceInput,
    reference: str,
) -> Optional[Declaration]:
    """Resolve one full id or uniquely named bare reference.

    Full ids never fall back to their bare suffix.  Bare references resolve
    only when exactly one source declaration has that name.  Ambiguous,
    duplicate, empty, and wrongly prefixed references therefore have no
    authority effect in Phase 0A.
    """
    resolution = ensure_compiled(workspace).resolve_reference(reference)
    return resolution.declaration


def authoritative_superseded_ids(workspace: WorkspaceInput) -> Set[str]:
    """Return full ids excluded by authoritative ``supersedes`` relations."""
    compiled = ensure_compiled(workspace)
    superseded: Set[str] = set()
    for source in compiled.declarations:
        if source.status in EXCLUDED_STATUSES:
            continue
        if source.status != "active":
            continue
        for reference in source.relations().get("supersedes", []):
            target = resolve_unique_reference(compiled, reference)
            if target is not None:
                superseded.add(target.id)
    return superseded


def current_declarations(workspace: WorkspaceInput) -> List[Declaration]:
    """Return the shared v0.6 service set after safe supersede exclusion.

    This is a narrow compatibility helper, not the proposed ResolvedView.
    ``Workspace.active()`` retains its historical serviceable/non-excluded
    meaning for callers that need the unprojected source set.
    """
    compiled = ensure_compiled(workspace)
    superseded = authoritative_superseded_ids(compiled)
    return [
        declaration for declaration in compiled.declarations
        if declaration.status not in EXCLUDED_STATUSES
        if declaration.id not in superseded
    ]
