"""Minimal lifecycle-safe authority resolution for v0.6 read surfaces.

Phase 1 delegates lookup and structural safety to the internal
CompiledWorkspace.  A ``supersedes`` relation can affect serving only when its
source is active and uniquely identified, its target resolves uniquely and
exactly, and the edge does not participate in an active revision cycle.
Forks remain report-only and never select a winner.
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
    return {
        edge.target_id
        for edge in compiled.authoritative_supersedes
        if edge.target_id is not None
    }


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
