"""Internal deterministic workspace compilation through experimental Phase 6.

This module is deliberately not re-exported from :mod:`memdsl`.  It provides
the indexed, rebuildable representation used by the existing v0.6 read
surfaces without creating a public ``CompiledWorkspace`` API commitment yet.
Source declarations remain authoritative; every object here can be discarded
and rebuilt from a :class:`memdsl.model.Workspace`.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple, Union

from memdsl.lexical import query_terms
from memdsl.model import (
    EDGE_LIFECYCLE_ACTIONS,
    Declaration,
    EdgeLifecycleEvent,
    ExplicitEdge,
    EXCLUDED_STATUSES,
    RELATION_FIELDS,
    Workspace,
)


COMPILER_CONTRACT_VERSION = "memdsl.compiler.phase5.v1"
EXPLICIT_EDGE_COMPILER_CONTRACT_VERSION = "memdsl.compiler.phase6.experimental.v1"


@dataclass(frozen=True)
class RelationDescriptor:
    """Internal structural contract for one built-in relation."""

    name: str
    acyclic: bool = False
    authority_effect: str = "none"


RELATION_REGISTRY = MappingProxyType({
    name: RelationDescriptor(
        name=name,
        acyclic=name in {"supersedes", "revision_of"},
        authority_effect="exclude_target" if name == "supersedes" else "none",
    )
    for name in sorted(RELATION_FIELDS)
})


@dataclass(frozen=True)
class CompilationDiagnostic:
    """One stable-code compiler/link diagnostic.

    Codes are the compatibility contract.  Messages may become clearer over
    time, but are deterministic for a fixed source workspace.
    """

    code: str
    severity: str
    message: str
    file: str
    line: int
    decl_id: Optional[str] = None
    related_ids: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ReferenceResolution:
    """Deterministic result for a full-id or bare-name reference."""

    reference: str
    status: str
    declaration: Optional[Declaration] = None
    candidate_ids: Tuple[str, ...] = ()

    @property
    def target_id(self) -> Optional[str]:
        return self.declaration.id if self.declaration is not None else None


@dataclass(frozen=True)
class CompiledEdge:
    """One normalized relation occurrence derived from declaration source."""

    edge_id: str
    source_id: str
    relation: str
    target_ref: str
    target_id: Optional[str]
    status: str
    file: str
    line: int
    ordinal: int
    candidate_ids: Tuple[str, ...] = ()
    visibility: str = "legacy"
    record_id: str = ""
    declared_by_id: Optional[str] = None


@dataclass(frozen=True)
class CompiledEdgeLifecycleEvent:
    """One resolved append-only lifecycle event for an explicit Edge."""

    event_id: str
    edge_ref: str
    edge_id: Optional[str]
    action: str
    event_at: str
    status: str
    evidence: Mapping[str, object]
    replacement_ref: str
    replacement_id: Optional[str]
    file: str
    line: int


@dataclass(frozen=True)
class CompiledExplicitEdge:
    """Compiled first-class Edge with stable identity and lifecycle state."""

    edge_id: str
    record_id: str
    declared_by_ref: str
    declared_by_id: Optional[str]
    source_ref: str
    source_id: Optional[str]
    target_ref: str
    target_id: Optional[str]
    relation: str
    status: str
    lifecycle_status: str
    evidence: Mapping[str, object]
    lifecycle: Mapping[str, object]
    access_policy: Mapping[str, object]
    relation_stability: str
    authoritative: bool
    file: str
    line: int
    candidate_ids: Tuple[str, ...] = ()
    events: Tuple[CompiledEdgeLifecycleEvent, ...] = ()
    origin: str = "explicit_edge"

    @property
    def origin_ids(self) -> Tuple[str, ...]:
        return (self.record_id,)


@dataclass(frozen=True)
class UseResolution:
    """One deterministic document-level ``use`` resolution."""

    target: str
    status: str
    target_kind: str
    file: str
    line: int
    imported_modules: Tuple[str, ...] = ()
    imported_symbol_ids: Tuple[str, ...] = ()
    candidate_ids: Tuple[str, ...] = ()


DeclarationIndex = Mapping[str, Tuple[Declaration, ...]]
EdgeIndex = Mapping[str, Tuple[CompiledEdge, ...]]
ExplicitEdgeIndex = Mapping[str, Tuple[CompiledExplicitEdge, ...]]


@dataclass(frozen=True)
class CompiledWorkspace:
    """Internal immutable index envelope over one source workspace."""

    source_fingerprint: str
    declarations: Tuple[Declaration, ...]
    occurrences_by_id: DeclarationIndex
    resolved_by_id: Mapping[str, Declaration]
    by_name: DeclarationIndex
    by_module: DeclarationIndex
    by_type: DeclarationIndex
    by_runtime_role: DeclarationIndex
    by_status: DeclarationIndex
    by_subject: DeclarationIndex
    by_scope: DeclarationIndex
    aliases: DeclarationIndex
    searchable_declarations: Tuple[Declaration, ...]
    lexical_terms: DeclarationIndex
    outgoing: EdgeIndex
    incoming: EdgeIndex
    uses_by_file: Mapping[str, Tuple[UseResolution, ...]]
    workspace_schema_version: str
    linking_visibility: str
    enforcement_mode: str
    dialect_mapping_types: Tuple[str, ...]
    dialect_aliases: Mapping[str, Tuple[str, ...]]
    dialect_targets: Mapping[str, Tuple[str, ...]]
    diagnostics: Tuple[CompilationDiagnostic, ...]
    revision_cycle_edge_ids: frozenset
    authoritative_supersedes: Tuple[CompiledEdge, ...]
    explicit_edges: Tuple[CompiledExplicitEdge, ...]
    explicit_edges_by_id: Mapping[str, CompiledExplicitEdge]
    explicit_outgoing: ExplicitEdgeIndex
    explicit_incoming: ExplicitEdgeIndex
    authoritative_explicit_edges: Tuple[CompiledExplicitEdge, ...]
    edge_events_by_edge: Mapping[str, Tuple[CompiledEdgeLifecycleEvent, ...]]
    edge_relation_registry: Mapping[str, object]
    _legacy_incoming: EdgeIndex = field(repr=False, compare=False)
    _first_by_id: Mapping[str, Declaration] = field(repr=False, compare=False)
    _first_by_name: Mapping[str, Declaration] = field(repr=False, compare=False)
    _subject_routable: Mapping[int, bool] = field(repr=False, compare=False)
    workspace: Workspace = field(repr=False, compare=False)

    @property
    def files(self) -> Tuple[str, ...]:
        return tuple(self.workspace.files)

    @property
    def registry(self):
        return self.workspace.registry

    def resolve_reference(self, reference: str) -> ReferenceResolution:
        """Resolve exact full ids or unique bare names without suffix fallback."""
        if not isinstance(reference, str) or not reference:
            return ReferenceResolution(str(reference or ""), "not_found")
        if ":" in reference:
            candidates = self.occurrences_by_id.get(reference, ())
            if not candidates:
                bare = reference.split(":", 1)[1]
                mismatched = self.by_name.get(bare, ())
                if mismatched:
                    return ReferenceResolution(
                        reference,
                        "kind_mismatch",
                        candidate_ids=tuple(item.id for item in mismatched),
                    )
        else:
            candidates = self.by_name.get(reference, ())
        candidate_ids = tuple(item.id for item in candidates)
        if len(candidates) == 1:
            return ReferenceResolution(
                reference,
                "resolved",
                declaration=candidates[0],
                candidate_ids=candidate_ids,
            )
        if candidates:
            return ReferenceResolution(
                reference,
                "ambiguous",
                candidate_ids=candidate_ids,
            )
        return ReferenceResolution(reference, "not_found")

    def first_occurrence(self, reference: str) -> Optional[Declaration]:
        """Preserve the v0.6 first-match read behavior through an index.

        This compatibility lookup is intentionally separate from
        :meth:`resolve_reference`.  Compiler linking and authority must never
        use it because duplicate ids and ambiguous bare names are unresolved.
        """
        if not isinstance(reference, str) or not reference:
            return None
        if ":" in reference:
            return self._first_by_id.get(reference)
        return self._first_by_name.get(reference)

    def legacy_incoming(self, declaration: Declaration) -> Tuple[CompiledEdge, ...]:
        """Return the v0.6 explain-compatible incoming relation projection."""
        return tuple(
            edge for edge in self._legacy_incoming.get(declaration.id, ())
            if edge.source_id != declaration.id
        )

    def subject_is_routable(self, declaration: Declaration) -> bool:
        """Whether this declaration's subject may affect strict alias routing."""
        return self._subject_routable.get(id(declaration), True)


WorkspaceInput = Union[Workspace, CompiledWorkspace]


def ensure_compiled(source: WorkspaceInput) -> CompiledWorkspace:
    """Return ``source`` as a compiled workspace, compiling only if needed."""
    if isinstance(source, CompiledWorkspace):
        return source
    return compile_workspace(source)


def compile_workspace(
    source: Union[Workspace, Iterable[str], str, os.PathLike],
    *,
    paths: Optional[Sequence[str]] = None,
) -> CompiledWorkspace:
    """Compile a path-backed or pure in-memory workspace deterministically."""
    path_list: Tuple[str, ...]
    if isinstance(source, Workspace):
        workspace = source
        path_list = _normalized_paths(paths or ())
    else:
        raw_paths = [source] if isinstance(source, (str, os.PathLike)) else source
        path_list = _normalized_paths(raw_paths)
        workspace = Workspace.load(path_list)

    fingerprint = _compiled_fingerprint(workspace, path_list)
    declarations = tuple(workspace.declarations)

    occurrences_by_id: Dict[str, list] = {}
    by_name: Dict[str, list] = {}
    by_module: Dict[str, list] = {}
    by_type: Dict[str, list] = {}
    by_runtime_role: Dict[str, list] = {}
    by_status: Dict[str, list] = {}
    by_subject: Dict[str, list] = {}
    by_scope: Dict[str, list] = {}
    aliases: Dict[str, list] = {}
    lexical_terms: Dict[str, list] = {}
    searchable_declarations = []
    first_by_id: Dict[str, Declaration] = {}
    first_by_name: Dict[str, Declaration] = {}

    for declaration in declarations:
        _append(occurrences_by_id, declaration.id, declaration)
        _append(by_name, declaration.name, declaration)
        _append(by_module, declaration.module or "", declaration)
        _append(by_type, declaration.kind, declaration)
        _append(by_runtime_role, declaration.runtime_role, declaration)
        _append(by_status, declaration.status, declaration)
        if declaration.subject:
            _append(by_subject, declaration.subject, declaration)
        if declaration.scope:
            _append(by_scope, declaration.scope, declaration)
        first_by_id.setdefault(declaration.id, declaration)
        first_by_name.setdefault(declaration.name, declaration)
        if declaration.runtime_role == "symbol":
            raw_aliases = declaration.fields.get("aliases", [])
            if isinstance(raw_aliases, list):
                for alias in raw_aliases:
                    _append(aliases, str(alias).lower(), declaration)
        elif declaration.has_capability("searchable"):
            searchable_declarations.append(declaration)
            for term in dict.fromkeys(query_terms(declaration.searchable_text())):
                _append(lexical_terms, term, declaration)

    frozen_occurrences = _freeze_declaration_index(occurrences_by_id)
    frozen_names = _freeze_declaration_index(by_name)
    resolved_by_id = MappingProxyType({
        declaration_id: items[0]
        for declaration_id, items in frozen_occurrences.items()
        if len(items) == 1
    })

    def resolve(reference: str) -> ReferenceResolution:
        if ":" in reference:
            candidates = frozen_occurrences.get(reference, ())
            if not candidates:
                bare = reference.split(":", 1)[1]
                mismatched = frozen_names.get(bare, ())
                if mismatched:
                    return ReferenceResolution(
                        reference,
                        "kind_mismatch",
                        candidate_ids=tuple(item.id for item in mismatched),
                    )
        else:
            candidates = frozen_names.get(reference, ())
        candidate_ids = tuple(item.id for item in candidates)
        if len(candidates) == 1:
            return ReferenceResolution(
                reference,
                "resolved",
                declaration=candidates[0],
                candidate_ids=candidate_ids,
            )
        if candidates:
            return ReferenceResolution(
                reference,
                "ambiguous",
                candidate_ids=candidate_ids,
            )
        return ReferenceResolution(reference, "not_found")

    active_symbols_by_name: Dict[str, List[Declaration]] = {}
    for declaration in declarations:
        if (
            declaration.runtime_role == "symbol"
            and declaration.status == "active"
            and declaration.status not in EXCLUDED_STATUSES
        ):
            _append(active_symbols_by_name, declaration.name, declaration)
    (
        uses_by_file,
        visibility_by_declaration,
        link_diagnostics,
    ) = _compile_use_visibility(
        workspace=workspace,
        declarations=declarations,
        by_module=by_module,
        active_symbols_by_name=active_symbols_by_name,
    )

    def visible(source: Declaration, target: Declaration) -> bool:
        if workspace.linking_visibility == "legacy":
            return True
        if source.module == target.module:
            return True
        imported_modules, imported_symbols = visibility_by_declaration.get(
            id(source), (frozenset(), frozenset()))
        return bool(
            (target.module or "") in imported_modules
            or id(target) in imported_symbols
        )

    outgoing: Dict[str, list] = {}
    incoming: Dict[str, list] = {}
    legacy_incoming: Dict[str, list] = {}
    source_occurrences = {
        id(declaration): ordinal
        for ordinal, declaration in enumerate(
            sorted(declarations, key=_declaration_sort_key))
    }
    for declaration in declarations:
        ordinal = 0
        for relation, targets in declaration.relations().items():
            for target_ref in targets:
                resolution = resolve(target_ref)
                visibility = "legacy"
                edge_status = resolution.status
                target_id = resolution.target_id
                candidate_ids = resolution.candidate_ids
                if resolution.declaration is not None:
                    is_visible = visible(declaration, resolution.declaration)
                    visibility = "visible" if is_visible else "violation"
                    if not is_visible:
                        severity = (
                            "error"
                            if workspace.linking_visibility == "strict"
                            else "warning"
                        )
                        link_diagnostics.append(CompilationDiagnostic(
                            "visibility_violation",
                            severity,
                            f"relation '{relation}' target '{target_ref}' is "
                            f"outside module '{declaration.module or '(none)'}'; "
                            "add an exact module or symbol use",
                            declaration.file,
                            declaration.line,
                            declaration.id,
                            related_ids=(resolution.declaration.id,),
                        ))
                        if workspace.linking_visibility == "strict":
                            edge_status = "visibility_violation"
                            target_id = None
                            candidate_ids = (resolution.declaration.id,)
                edge = CompiledEdge(
                    edge_id=_edge_id(
                        declaration,
                        relation,
                        target_ref,
                        ordinal,
                        source_occurrences[id(declaration)],
                    ),
                    source_id=declaration.id,
                    relation=relation,
                    target_ref=target_ref,
                    target_id=target_id,
                    status=edge_status,
                    file=declaration.file,
                    line=declaration.line,
                    ordinal=ordinal,
                    candidate_ids=candidate_ids,
                    visibility=visibility,
                    record_id=declaration.id,
                    declared_by_id=declaration.id,
                )
                _append(outgoing, declaration.id, edge)
                if edge.target_id is not None:
                    _append(incoming, edge.target_id, edge)

                # Preserve the v0.6 explain projection without rescanning all
                # declarations.  Full ids match exactly; bare names fan out to
                # every legacy name match even when compiler linking marks the
                # reference ambiguous.
                legacy_targets = (
                    ()
                    if edge.status == "visibility_violation"
                    else frozen_occurrences.get(target_ref, ())
                    if ":" in target_ref
                    else frozen_names.get(target_ref, ())
                )
                for target_id in dict.fromkeys(item.id for item in legacy_targets):
                    _append(legacy_incoming, target_id, edge)
                ordinal += 1

    frozen_outgoing = _freeze_edge_index(outgoing)
    frozen_incoming = _freeze_edge_index(incoming)
    all_edges = tuple(
        edge for edges in frozen_outgoing.values() for edge in edges)
    unique_source_ids = {
        declaration_id
        for declaration_id, items in frozen_occurrences.items()
        if len(items) == 1
    }
    revision_edges = tuple(
        edge for edge in all_edges
        if RELATION_REGISTRY[edge.relation].acyclic
        if edge.status == "resolved"
        if edge.source_id in unique_source_ids
    )
    revision_components = _cyclic_components(revision_edges)
    revision_cycle_edge_ids = frozenset(
        edge.edge_id
        for component in revision_components
        for edge in revision_edges
        if edge.source_id in component and edge.target_id in component
    )

    active_revision_edges = tuple(
        edge for edge in revision_edges
        if _is_active_source(edge, resolved_by_id)
    )
    active_cycle_components = _cyclic_components(active_revision_edges)
    authority_cycle_edge_ids = frozenset(
        edge.edge_id
        for component in active_cycle_components
        for edge in active_revision_edges
        if edge.source_id in component and edge.target_id in component
    )
    authoritative_supersedes = tuple(
        edge for edge in all_edges
        if edge.relation == "supersedes"
        if edge.status == "resolved"
        if edge.source_id in unique_source_ids
        if _is_active_source(edge, resolved_by_id)
        if edge.edge_id not in authority_cycle_edge_ids
    )
    (
        explicit_edges,
        explicit_edges_by_id,
        explicit_outgoing,
        explicit_incoming,
        authoritative_explicit_edges,
        edge_events_by_edge,
        explicit_edge_diagnostics,
    ) = _compile_explicit_edges(
        workspace=workspace,
        resolve=resolve,
    )
    link_diagnostics.extend(explicit_edge_diagnostics)
    subject_routable, subject_diagnostics = _compile_subject_visibility(
        workspace=workspace,
        declarations=declarations,
        active_symbols_by_name=active_symbols_by_name,
        visible=visible,
    )
    link_diagnostics.extend(subject_diagnostics)
    (
        dialect_mapping_types,
        dialect_aliases,
        dialect_targets,
        dialect_diagnostics,
    ) = _compile_dialect_mappings(
        workspace=workspace,
        declarations=declarations,
        active_symbols_by_name=active_symbols_by_name,
        authoritative_supersedes=authoritative_supersedes,
        visible=visible,
    )
    link_diagnostics.extend(dialect_diagnostics)
    diagnostics = _compile_diagnostics(
        declarations=declarations,
        occurrences_by_id=frozen_occurrences,
        resolved_by_id=resolved_by_id,
        edges=all_edges,
        revision_edges=revision_edges,
        revision_components=revision_components,
        authoritative_supersedes=authoritative_supersedes,
        additional_diagnostics=tuple(link_diagnostics),
    )

    return CompiledWorkspace(
        source_fingerprint=fingerprint,
        declarations=declarations,
        occurrences_by_id=frozen_occurrences,
        resolved_by_id=resolved_by_id,
        by_name=frozen_names,
        by_module=_freeze_declaration_index(by_module),
        by_type=_freeze_declaration_index(by_type),
        by_runtime_role=_freeze_declaration_index(by_runtime_role),
        by_status=_freeze_declaration_index(by_status),
        by_subject=_freeze_declaration_index(by_subject),
        by_scope=_freeze_declaration_index(by_scope),
        aliases=_freeze_declaration_index(aliases),
        searchable_declarations=tuple(sorted(
            searchable_declarations, key=_declaration_sort_key)),
        lexical_terms=_freeze_declaration_index(lexical_terms),
        outgoing=frozen_outgoing,
        incoming=frozen_incoming,
        uses_by_file=uses_by_file,
        workspace_schema_version=workspace.schema_version,
        linking_visibility=workspace.linking_visibility,
        enforcement_mode=workspace.enforcement_mode,
        dialect_mapping_types=dialect_mapping_types,
        dialect_aliases=dialect_aliases,
        dialect_targets=dialect_targets,
        diagnostics=diagnostics,
        revision_cycle_edge_ids=revision_cycle_edge_ids,
        authoritative_supersedes=authoritative_supersedes,
        explicit_edges=explicit_edges,
        explicit_edges_by_id=explicit_edges_by_id,
        explicit_outgoing=explicit_outgoing,
        explicit_incoming=explicit_incoming,
        authoritative_explicit_edges=authoritative_explicit_edges,
        edge_events_by_edge=edge_events_by_edge,
        edge_relation_registry=MappingProxyType({
            descriptor.name: descriptor
            for descriptor in workspace.registry.edge_relation_descriptors()
        }),
        _legacy_incoming=_freeze_edge_index(
            legacy_incoming, preserve_input_order=True),
        _first_by_id=MappingProxyType(dict(first_by_id)),
        _first_by_name=MappingProxyType(dict(first_by_name)),
        _subject_routable=MappingProxyType(dict(subject_routable)),
        workspace=workspace,
    )


def _compile_explicit_edges(
    *,
    workspace: Workspace,
    resolve,
) -> tuple:
    """Compile Phase 6 explicit Edges without changing legacy node authority."""
    diagnostics: List[CompilationDiagnostic] = []
    occurrences: Dict[str, List[ExplicitEdge]] = {}
    for edge in workspace.explicit_edges:
        occurrences.setdefault(edge.id, []).append(edge)

    unique_edges: Dict[str, ExplicitEdge] = {}
    for edge_id, items in sorted(occurrences.items()):
        ordered = sorted(items, key=_source_item_sort_key)
        if len(ordered) == 1:
            unique_edges[edge_id] = ordered[0]
            continue
        first = ordered[0]
        for duplicate in ordered[1:]:
            diagnostics.append(CompilationDiagnostic(
                "duplicate_explicit_edge_id",
                "error",
                f"'{edge_id}' already declared at {first.file}:{first.line}",
                duplicate.file,
                duplicate.line,
                edge_id,
                related_ids=(edge_id,),
            ))

    event_occurrences: Dict[str, List[EdgeLifecycleEvent]] = {}
    for event in workspace.edge_events:
        event_occurrences.setdefault(event.id, []).append(event)
    valid_event_keys = {
        (event.file, event.line, event.id)
        for event in workspace.edge_events
        if len(event_occurrences[event.id]) == 1
        if _explicit_edge_event_structurally_valid(event)
    }

    def resolve_edge(reference: str) -> Tuple[Optional[str], Tuple[str, ...], str]:
        raw = str(reference or "")
        canonical = (
            raw
            if raw.startswith("relation_edge:")
            else f"relation_edge:{raw.split(':', 1)[-1]}"
        )
        matches = sorted(
            [edge_id for edge_id in occurrences if edge_id == canonical]
        )
        if len(matches) == 1 and len(occurrences[matches[0]]) == 1:
            return matches[0], tuple(matches), "resolved"
        if matches:
            return None, tuple(matches), "ambiguous"
        return None, (), "not_found"

    compiled_events: List[CompiledEdgeLifecycleEvent] = []
    for event in sorted(workspace.edge_events, key=_edge_event_sort_key):
        edge_id, candidates, edge_status = resolve_edge(event.edge_ref)
        replacement_id: Optional[str] = None
        replacement_status = "resolved"
        if event.action == "supersede":
            replacement_id, _, replacement_status = resolve_edge(event.replacement_ref)
        compiled_event = CompiledEdgeLifecycleEvent(
            event_id=event.id,
            edge_ref=event.edge_ref,
            edge_id=edge_id,
            action=event.action,
            event_at=event.event_at,
            status=event.status,
            evidence=MappingProxyType(dict(event.evidence or {})),
            replacement_ref=event.replacement_ref,
            replacement_id=replacement_id,
            file=event.file,
            line=event.line,
        )
        compiled_events.append(compiled_event)
        if edge_status != "resolved":
            diagnostics.append(CompilationDiagnostic(
                "unresolved_edge_event_target"
                if edge_status == "not_found" else "ambiguous_edge_event_target",
                "error",
                f"edge lifecycle event '{event.id}' cannot resolve Edge "
                f"'{event.edge_ref}'",
                event.file,
                event.line,
                event.id,
                related_ids=candidates,
            ))
        if event.action == "supersede" and replacement_status != "resolved":
            diagnostics.append(CompilationDiagnostic(
                "unresolved_edge_replacement",
                "error",
                f"edge lifecycle event '{event.id}' cannot resolve replacement "
                f"Edge '{event.replacement_ref}'",
                event.file,
                event.line,
                event.id,
            ))

    events_by_edge: Dict[str, List[CompiledEdgeLifecycleEvent]] = {}
    for event in compiled_events:
        if event.edge_id is not None:
            events_by_edge.setdefault(event.edge_id, []).append(event)
    frozen_events = MappingProxyType({
        edge_id: tuple(sorted(events, key=_compiled_edge_event_sort_key))
        for edge_id, events in sorted(events_by_edge.items())
    })

    compiled: List[CompiledExplicitEdge] = []
    outgoing: Dict[str, list] = {}
    incoming: Dict[str, list] = {}
    by_id: Dict[str, CompiledExplicitEdge] = {}
    for edge_id, edge in sorted(unique_edges.items()):
        source_resolution = resolve(edge.source_ref)
        target_resolution = resolve(edge.target_ref)
        declared_by_resolution = resolve(edge.declared_by_ref)
        relation_descriptor = workspace.registry.resolve_edge_relation(edge.relation)
        resolution_status = "resolved"
        candidates = tuple(sorted(set(
            declared_by_resolution.candidate_ids
            + source_resolution.candidate_ids
            + target_resolution.candidate_ids
        )))
        if relation_descriptor is None:
            resolution_status = "unknown_relation"
        elif declared_by_resolution.status != "resolved":
            resolution_status = f"declared_by_{declared_by_resolution.status}"
        elif source_resolution.status != "resolved":
            resolution_status = f"source_{source_resolution.status}"
        elif target_resolution.status != "resolved":
            resolution_status = f"target_{target_resolution.status}"

        lifecycle_status = edge.status
        applied_events = []
        lifecycle = dict(edge.lifecycle)
        for event in frozen_events.get(edge_id, ()):
            if (
                (event.file, event.line, event.event_id) not in valid_event_keys
                or event.status != "active"
                or event.action not in EDGE_LIFECYCLE_ACTIONS
            ):
                continue
            if event.action == "confirm":
                lifecycle_status = "active"
            elif event.action == "dispute":
                lifecycle_status = "disputed"
            elif event.action == "retract":
                lifecycle_status = "retracted"
            elif event.action == "supersede" and event.replacement_id:
                lifecycle_status = "superseded"
                lifecycle["superseded_by"] = event.replacement_id
            lifecycle["last_event"] = event.event_id
            lifecycle["last_event_at"] = event.event_at
            applied_events.append(event)
        lifecycle["status"] = lifecycle_status

        source_decl = source_resolution.declaration
        target_decl = target_resolution.declaration
        endpoint_active = bool(
            source_decl is not None
            and target_decl is not None
            and source_decl.status == "active"
            and target_decl.status == "active"
            and source_decl.status not in EXCLUDED_STATUSES
            and target_decl.status not in EXCLUDED_STATUSES
        )
        authoritative = bool(
            resolution_status == "resolved"
            and lifecycle_status == "active"
            and endpoint_active
            and _explicit_edge_structurally_valid(edge)
        )
        item = CompiledExplicitEdge(
            edge_id=edge_id,
            record_id=edge_id,
            declared_by_ref=edge.declared_by_ref,
            declared_by_id=declared_by_resolution.target_id,
            source_ref=edge.source_ref,
            source_id=source_resolution.target_id,
            target_ref=edge.target_ref,
            target_id=target_resolution.target_id,
            relation=edge.relation,
            status=resolution_status,
            lifecycle_status=lifecycle_status,
            evidence=MappingProxyType(dict(edge.evidence or {})),
            lifecycle=MappingProxyType(lifecycle),
            access_policy=MappingProxyType(dict(edge.access_policy)),
            relation_stability=(
                relation_descriptor.stability if relation_descriptor else "unknown"),
            authoritative=authoritative,
            file=edge.file,
            line=edge.line,
            candidate_ids=candidates,
            events=tuple(applied_events),
        )
        compiled.append(item)
        by_id[edge_id] = item
        if resolution_status != "resolved":
            code = {
                "unknown_relation": "unknown_edge_relation",
                "declared_by_ambiguous": "ambiguous_edge_declared_by",
                "declared_by_kind_mismatch": "edge_declared_by_kind_mismatch",
                "declared_by_not_found": "unresolved_edge_declared_by",
                "source_ambiguous": "ambiguous_edge_source",
                "source_kind_mismatch": "edge_source_kind_mismatch",
                "source_not_found": "unresolved_edge_source",
                "target_ambiguous": "ambiguous_edge_target",
                "target_kind_mismatch": "edge_target_kind_mismatch",
                "target_not_found": "unresolved_edge_target",
            }.get(resolution_status, "invalid_explicit_edge")
            diagnostics.append(CompilationDiagnostic(
                code,
                "error",
                f"explicit Edge '{edge_id}' could not compile: {resolution_status}",
                edge.file,
                edge.line,
                edge_id,
                related_ids=candidates,
            ))
        if authoritative and item.source_id and item.target_id:
            _append(outgoing, item.source_id, item)
            _append(incoming, item.target_id, item)

    authoritative = tuple(
        item for item in compiled if item.authoritative)
    return (
        tuple(compiled),
        MappingProxyType(by_id),
        _freeze_explicit_edge_index(outgoing),
        _freeze_explicit_edge_index(incoming),
        authoritative,
        frozen_events,
        diagnostics,
    )


def _explicit_edge_structurally_valid(edge: ExplicitEdge) -> bool:
    allowed = {
        "declared_by", "source", "target", "relation", "evidence",
        "lifecycle", "status", "scope", "access_policy", "access",
    }
    if set(edge.fields) - allowed:
        return False
    if any(
        not value or ":" not in value
        for value in (
            edge.declared_by_ref, edge.source_ref, edge.target_ref)
    ):
        return False
    lifecycle = edge.fields.get("lifecycle")
    if not isinstance(lifecycle, dict):
        return False
    if edge.status not in {
        "active", "candidate", "disputed", "quarantined", "retracted",
        "superseded",
    }:
        return False
    if not _valid_edge_evidence(edge.evidence):
        return False
    raw_access = edge.fields.get(
        "access_policy", edge.fields.get("access"))
    return _valid_edge_access_policy(raw_access)


def _explicit_edge_event_structurally_valid(
    event: EdgeLifecycleEvent,
) -> bool:
    allowed = {
        "edge", "action", "event_at", "replacement", "evidence",
        "lifecycle", "status",
    }
    if set(event.fields) - allowed:
        return False
    if not event.edge_ref or event.action not in EDGE_LIFECYCLE_ACTIONS:
        return False
    if not isinstance(event.fields.get("lifecycle"), dict):
        return False
    if event.status != "active" or not _valid_edge_evidence(event.evidence):
        return False
    try:
        _dt.datetime.fromisoformat(event.event_at.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return False
    if event.action == "supersede" and not event.replacement_ref:
        return False
    return True


def _valid_edge_evidence(value) -> bool:
    return bool(
        isinstance(value, Mapping)
        and isinstance(value.get("source"), str)
        and value.get("source")
        and isinstance(value.get("quote"), str)
        and value.get("quote")
    )


def _valid_edge_access_policy(value) -> bool:
    if value is None or value == {}:
        return True
    if not isinstance(value, Mapping):
        return False
    if set(value) - {"readers", "writers", "reviewers"}:
        return False
    return all(
        isinstance(items, list)
        and all(isinstance(item, str) for item in items)
        for items in value.values()
    )


def _compile_use_visibility(
    *,
    workspace: Workspace,
    declarations: Tuple[Declaration, ...],
    by_module: Mapping[str, Sequence[Declaration]],
    active_symbols_by_name: Mapping[str, Sequence[Declaration]],
) -> Tuple[
    Mapping[str, Tuple[UseResolution, ...]],
    Mapping[int, Tuple[frozenset, frozenset]],
    List[CompilationDiagnostic],
]:
    """Resolve document uses before declaration references are linked."""
    diagnostics: List[CompilationDiagnostic] = []
    contexts: Dict[tuple, dict] = {}

    for document in workspace.documents:
        key = (
            str(document.file),
            document.module or "",
            tuple(document.uses),
            tuple(statement.value for statement in document.module_statements),
        )
        contexts[key] = {
            "file": str(document.file),
            "module": document.module or "",
            "uses": tuple(document.uses),
            "use_lines": tuple(
                statement.line for statement in document.use_statements),
            "module_statements": tuple(document.module_statements),
        }

    for declaration in declarations:
        key = (
            str(declaration.file),
            declaration.module or "",
            tuple(declaration.uses),
            tuple(declaration.module_statements),
        )
        contexts.setdefault(key, {
            "file": str(declaration.file),
            "module": declaration.module or "",
            "uses": tuple(declaration.uses),
            "use_lines": tuple(declaration.line for _ in declaration.uses),
            "module_statements": tuple(
                _StatementValue(value, declaration.line)
                for value in declaration.module_statements
            ),
        })

    uses_by_file: Dict[str, List[UseResolution]] = {}
    context_imports: Dict[tuple, Tuple[frozenset, frozenset]] = {}
    module_names = {name for name in by_module if name}
    severity = "error" if workspace.linking_visibility == "strict" else "warning"

    for key, context in sorted(contexts.items(), key=lambda item: item[0]):
        module_statements = context["module_statements"]
        invalid_multi_module = len(module_statements) > 1
        if workspace.linking_visibility != "legacy" and invalid_multi_module:
            statement = module_statements[1]
            diagnostics.append(CompilationDiagnostic(
                "multiple_module_statements",
                severity,
                "workspace v2 allows at most one module statement per source "
                "file; split the file or keep one module declaration",
                context["file"],
                statement.line,
            ))

        imported_modules: Set[str] = set()
        imported_symbols: Set[int] = set()
        resolutions: List[UseResolution] = []
        for index, target in enumerate(context["uses"]):
            line = (
                context["use_lines"][index]
                if index < len(context["use_lines"])
                else 0
            )
            if workspace.linking_visibility == "legacy":
                resolutions.append(UseResolution(
                    target=target,
                    status="recorded",
                    target_kind="",
                    file=context["file"],
                    line=line,
                ))
                continue

            module_match = target in module_names
            symbol_matches = tuple(active_symbols_by_name.get(target, ()))
            candidate_ids = tuple(sorted(
                ([f"module:{target}"] if module_match else [])
                + [item.id for item in symbol_matches]
            ))
            if "*" in target:
                status = "unsupported_wildcard"
                target_kind = ""
                diagnostics.append(CompilationDiagnostic(
                    "unsupported_use_wildcard",
                    severity,
                    f"use target '{target}' uses a wildcard; Phase 4 supports "
                    "only exact module or active symbol names",
                    context["file"],
                    line,
                    related_ids=candidate_ids,
                ))
            elif (module_match and symbol_matches) or len(symbol_matches) > 1:
                status = "ambiguous"
                target_kind = ""
                diagnostics.append(CompilationDiagnostic(
                    "ambiguous_use_target",
                    severity,
                    f"use target '{target}' is ambiguous between: "
                    + ", ".join(candidate_ids),
                    context["file"],
                    line,
                    related_ids=candidate_ids,
                ))
            elif module_match:
                status = "resolved"
                target_kind = "module"
                if not (
                    workspace.linking_visibility == "strict"
                    and invalid_multi_module
                ):
                    imported_modules.add(target)
            elif len(symbol_matches) == 1:
                status = "resolved"
                target_kind = "symbol"
                if not (
                    workspace.linking_visibility == "strict"
                    and invalid_multi_module
                ):
                    imported_symbols.add(id(symbol_matches[0]))
            else:
                status = "not_found"
                target_kind = ""
                diagnostics.append(CompilationDiagnostic(
                    "unresolved_use_target",
                    severity,
                    f"use target '{target}' is not an exact module or active "
                    "symbol name",
                    context["file"],
                    line,
                ))
            resolutions.append(UseResolution(
                target=target,
                status=status,
                target_kind=target_kind,
                file=context["file"],
                line=line,
                imported_modules=(
                    (target,)
                    if target_kind == "module" and target in imported_modules
                    else ()
                ),
                imported_symbol_ids=(
                    (symbol_matches[0].id,)
                    if (
                        target_kind == "symbol"
                        and len(symbol_matches) == 1
                        and id(symbol_matches[0]) in imported_symbols
                    )
                    else ()
                ),
                candidate_ids=candidate_ids,
            ))
        uses_by_file.setdefault(context["file"], []).extend(resolutions)
        context_imports[key] = (
            frozenset(imported_modules),
            frozenset(imported_symbols),
        )

    visibility_by_declaration = {}
    for declaration in declarations:
        key = (
            str(declaration.file),
            declaration.module or "",
            tuple(declaration.uses),
            tuple(declaration.module_statements),
        )
        visibility_by_declaration[id(declaration)] = context_imports.get(
            key, (frozenset(), frozenset()))

    frozen_uses = MappingProxyType({
        file: tuple(sorted(items, key=_use_sort_key))
        for file, items in sorted(uses_by_file.items())
    })
    return frozen_uses, visibility_by_declaration, diagnostics


@dataclass(frozen=True)
class _StatementValue:
    value: str
    line: int


def _compile_subject_visibility(
    *,
    workspace: Workspace,
    declarations: Tuple[Declaration, ...],
    active_symbols_by_name: Mapping[str, Sequence[Declaration]],
    visible,
) -> Tuple[Dict[int, bool], List[CompilationDiagnostic]]:
    routable: Dict[int, bool] = {}
    diagnostics: List[CompilationDiagnostic] = []
    for declaration in declarations:
        if not declaration.subject or workspace.linking_visibility == "legacy":
            routable[id(declaration)] = True
            continue
        candidates = tuple(active_symbols_by_name.get(declaration.subject, ()))
        if len(candidates) != 1:
            routable[id(declaration)] = workspace.linking_visibility != "strict"
            continue
        is_visible = visible(declaration, candidates[0])
        routable[id(declaration)] = (
            is_visible or workspace.linking_visibility != "strict")
        if not is_visible:
            diagnostics.append(CompilationDiagnostic(
                "visibility_violation",
                "error" if workspace.linking_visibility == "strict" else "warning",
                f"subject '{declaration.subject}' is outside module "
                f"'{declaration.module or '(none)'}'; add an exact symbol use",
                declaration.file,
                declaration.line,
                declaration.id,
                related_ids=(candidates[0].id,),
            ))
    return routable, diagnostics


def _compile_dialect_mappings(
    *,
    workspace: Workspace,
    declarations: Tuple[Declaration, ...],
    active_symbols_by_name: Mapping[str, Sequence[Declaration]],
    authoritative_supersedes: Tuple[CompiledEdge, ...],
    visible,
) -> Tuple[
    Tuple[str, ...],
    Mapping[str, Tuple[str, ...]],
    Mapping[str, Tuple[str, ...]],
    List[CompilationDiagnostic],
]:
    mapping_types = tuple(sorted(
        descriptor.name
        for descriptor in workspace.registry.descriptors()
        if descriptor.has_capability("dialect_mapping")
    ))
    diagnostics: List[CompilationDiagnostic] = []
    if not mapping_types:
        return (
            (), MappingProxyType({}), MappingProxyType({}), diagnostics)

    superseded_ids = {
        edge.target_id for edge in authoritative_supersedes if edge.target_id}
    id_counts: Dict[str, int] = {}
    direct_routing: Dict[str, Set[str]] = {}
    direct_public: Dict[str, Set[str]] = {}
    for declaration in declarations:
        id_counts[declaration.id] = id_counts.get(declaration.id, 0) + 1
        if (
            declaration.runtime_role != "symbol"
            or declaration.status != "active"
            or declaration.status in EXCLUDED_STATUSES
            or declaration.id in superseded_ids
        ):
            continue
        aliases = declaration.fields.get("aliases")
        if not isinstance(aliases, list):
            continue
        for alias in aliases:
            phrase = str(alias).strip().lower()
            if not phrase:
                continue
            direct_routing.setdefault(phrase, set()).add(declaration.name)
            if not declaration.access_policy:
                direct_public.setdefault(phrase, set()).add(declaration.name)

    mapping_targets: Dict[str, Set[str]] = {}
    mapping_sources: Dict[str, List[Declaration]] = {}
    for declaration in declarations:
        descriptor = declaration.type_descriptor
        if descriptor is None or not descriptor.has_capability("dialect_mapping"):
            continue
        target = declaration.field("target")
        phrases = declaration.field("phrases")
        polarity = declaration.field("polarity", "positive")
        valid_phrases = (
            isinstance(phrases, list)
            and bool(phrases)
            and all(isinstance(item, str) and item.strip() for item in phrases)
        )
        if (
            not isinstance(target, str)
            or not target.strip()
            or not valid_phrases
            or declaration.evidence is None
        ):
            diagnostics.append(CompilationDiagnostic(
                "invalid_dialect_mapping",
                "error",
                f"dialect mapping '{declaration.id}' requires a non-empty "
                "string target, a non-empty list of string phrases, and an "
                "evidence block",
                declaration.file,
                declaration.line,
                declaration.id,
            ))
            continue
        if polarity != "positive":
            diagnostics.append(CompilationDiagnostic(
                "unsupported_dialect_polarity",
                "error",
                f"dialect mapping '{declaration.id}' uses unsupported polarity "
                f"'{polarity}'; Phase 4 supports only positive mappings",
                declaration.file,
                declaration.line,
                declaration.id,
            ))
            continue
        target_name = target.strip()
        target_candidates = tuple(active_symbols_by_name.get(target_name, ()))
        if len(target_candidates) != 1:
            diagnostics.append(CompilationDiagnostic(
                "invalid_dialect_mapping",
                "error",
                f"dialect mapping '{declaration.id}' target '{target_name}' "
                "must resolve to exactly one active symbol name",
                declaration.file,
                declaration.line,
                declaration.id,
                related_ids=tuple(sorted(item.id for item in target_candidates)),
            ))
            continue
        target_declaration = target_candidates[0]
        is_visible = visible(declaration, target_declaration)
        if workspace.linking_visibility != "legacy" and not is_visible:
            diagnostics.append(CompilationDiagnostic(
                "visibility_violation",
                "error" if workspace.linking_visibility == "strict" else "warning",
                f"dialect target '{target_name}' is outside module "
                f"'{declaration.module or '(none)'}'; add an exact symbol use",
                declaration.file,
                declaration.line,
                declaration.id,
                related_ids=(target_declaration.id,),
            ))
        route_allowed = bool(
            declaration.status == "active"
            and declaration.status not in EXCLUDED_STATUSES
            and declaration.id not in superseded_ids
            and id_counts.get(declaration.id) == 1
            and not declaration.access_policy
            and not target_declaration.access_policy
            and (is_visible or workspace.linking_visibility != "strict")
        )
        if not route_allowed:
            continue
        for raw_phrase in phrases:
            phrase = raw_phrase.strip().lower()
            mapping_targets.setdefault(phrase, set()).add(target_name)
            mapping_sources.setdefault(phrase, []).append(declaration)

    dialect_aliases: Dict[str, Tuple[str, ...]] = {}
    dialect_targets: Dict[str, Tuple[str, ...]] = {}
    for phrase in sorted(mapping_targets):
        mapped = set(mapping_targets[phrase])
        routing_targets = mapped | direct_routing.get(phrase, set())
        public_targets = mapped | direct_public.get(phrase, set())
        private_conflict = bool(
            direct_routing.get(phrase, set()) - direct_public.get(phrase, set()))
        if len(routing_targets) > 1:
            related = tuple(sorted(routing_targets))
            for declaration in sorted(
                mapping_sources[phrase], key=_declaration_sort_key):
                diagnostics.append(CompilationDiagnostic(
                    "ambiguous_dialect_mapping",
                    "warning",
                    f"dialect phrase '{phrase}' maps to multiple active symbols: "
                    + ", ".join(related),
                    declaration.file,
                    declaration.line,
                    declaration.id,
                    related_ids=related,
                ))
            if not private_conflict:
                dialect_targets[phrase] = tuple(sorted(public_targets))
            continue
        target_tuple = tuple(sorted(mapped))
        dialect_aliases[phrase] = target_tuple
        dialect_targets[phrase] = target_tuple

    return (
        mapping_types,
        MappingProxyType(dialect_aliases),
        MappingProxyType(dialect_targets),
        diagnostics,
    )


def _compile_diagnostics(
    *,
    declarations: Tuple[Declaration, ...],
    occurrences_by_id: DeclarationIndex,
    resolved_by_id: Mapping[str, Declaration],
    edges: Tuple[CompiledEdge, ...],
    revision_edges: Tuple[CompiledEdge, ...],
    revision_components: Tuple[frozenset, ...],
    authoritative_supersedes: Tuple[CompiledEdge, ...],
    additional_diagnostics: Tuple[CompilationDiagnostic, ...] = (),
) -> Tuple[CompilationDiagnostic, ...]:
    diagnostics = list(additional_diagnostics)

    for declaration_id, occurrences in occurrences_by_id.items():
        if len(occurrences) < 2:
            continue
        first = occurrences[0]
        for duplicate in occurrences[1:]:
            diagnostics.append(CompilationDiagnostic(
                "duplicate_declaration_id",
                "error",
                f"'{declaration_id}' already declared at {first.file}:{first.line}",
                duplicate.file,
                duplicate.line,
                declaration_id,
                related_ids=(declaration_id,),
            ))

    for declaration in declarations:
        raw_relations = declaration.fields.get("relations")
        if not isinstance(raw_relations, dict):
            continue
        for relation in sorted(set(raw_relations) - set(RELATION_REGISTRY)):
            diagnostics.append(CompilationDiagnostic(
                "unknown_relation",
                "error",
                f"memory '{declaration.id}' uses unknown relation '{relation}'",
                declaration.file,
                declaration.line,
                declaration.id,
            ))

    for edge in edges:
        if edge.status == "resolved":
            continue
        if edge.status == "ambiguous":
            candidates = ", ".join(sorted(set(edge.candidate_ids)))
            diagnostics.append(CompilationDiagnostic(
                "ambiguous_relation_target",
                "error",
                f"relation '{edge.relation}' target '{edge.target_ref}' is ambiguous"
                + (f": {candidates}" if candidates else ""),
                edge.file,
                edge.line,
                edge.source_id,
                related_ids=tuple(sorted(set(edge.candidate_ids))),
            ))
        elif edge.status == "kind_mismatch":
            candidates = ", ".join(sorted(set(edge.candidate_ids)))
            diagnostics.append(CompilationDiagnostic(
                "relation_target_kind_mismatch",
                "error",
                f"relation '{edge.relation}' target '{edge.target_ref}' has the "
                f"wrong type prefix; available target(s): {candidates}",
                edge.file,
                edge.line,
                edge.source_id,
                related_ids=tuple(sorted(set(edge.candidate_ids))),
            ))
        elif edge.status == "visibility_violation":
            continue
        else:
            diagnostics.append(CompilationDiagnostic(
                "unresolved_symbol",
                "error",
                f"relation '{edge.relation}' points to unknown declaration "
                f"'{edge.target_ref}'",
                edge.file,
                edge.line,
                edge.source_id,
            ))

    component_by_node = {
        node: component
        for component in revision_components
        for node in component
    }
    cycle_paths = {
        component: _canonical_cycle_path(component, revision_edges)
        for component in revision_components
    }
    for edge in revision_edges:
        component = component_by_node.get(edge.source_id)
        if component is None or edge.target_id not in component:
            continue
        path = cycle_paths[component]
        diagnostics.append(CompilationDiagnostic(
            "revision_cycle",
            "error",
            "revision relation cycle detected: " + " -> ".join(path),
            edge.file,
            edge.line,
            edge.source_id,
            related_ids=tuple(path[:-1]),
        ))

    successors_by_target: Dict[str, Dict[str, CompiledEdge]] = {}
    for edge in authoritative_supersedes:
        if edge.target_id is None:
            continue
        successors_by_target.setdefault(edge.target_id, {}).setdefault(
            edge.source_id, edge)
    for target_id, successors in sorted(successors_by_target.items()):
        if len(successors) < 2:
            continue
        successor_ids = tuple(sorted(successors))
        for source_id in successor_ids:
            edge = successors[source_id]
            diagnostics.append(CompilationDiagnostic(
                "supersedes_fork",
                "warning",
                f"'{target_id}' is superseded by multiple active declarations: "
                + ", ".join(successor_ids),
                edge.file,
                edge.line,
                source_id,
                related_ids=(target_id,) + successor_ids,
            ))

    return tuple(sorted(diagnostics, key=_diagnostic_sort_key))


def _is_active_source(
    edge: CompiledEdge,
    resolved_by_id: Mapping[str, Declaration],
) -> bool:
    source = resolved_by_id.get(edge.source_id)
    return bool(
        source is not None
        and source.status == "active"
        and source.status not in EXCLUDED_STATUSES
    )


def _cyclic_components(
    edges: Tuple[CompiledEdge, ...],
) -> Tuple[frozenset, ...]:
    """Return deterministic strongly connected components that contain a cycle."""
    adjacency: Dict[str, set] = {}
    reverse: Dict[str, set] = {}
    nodes = set()
    self_loops = set()
    for edge in edges:
        if edge.target_id is None:
            continue
        nodes.update((edge.source_id, edge.target_id))
        adjacency.setdefault(edge.source_id, set()).add(edge.target_id)
        reverse.setdefault(edge.target_id, set()).add(edge.source_id)
        if edge.source_id == edge.target_id:
            self_loops.add(edge.source_id)

    ordered_adjacency = {
        node: tuple(sorted(adjacency.get(node, ()))) for node in nodes}
    ordered_reverse = {
        node: tuple(sorted(reverse.get(node, ()))) for node in nodes}

    visited = set()
    finish = []
    for root in sorted(nodes):
        if root in visited:
            continue
        visited.add(root)
        stack = [(root, 0)]
        while stack:
            node, index = stack[-1]
            neighbors = ordered_adjacency[node]
            if index < len(neighbors):
                neighbor = neighbors[index]
                stack[-1] = (node, index + 1)
                if neighbor not in visited:
                    visited.add(neighbor)
                    stack.append((neighbor, 0))
                continue
            finish.append(node)
            stack.pop()

    assigned = set()
    components = []
    for root in reversed(finish):
        if root in assigned:
            continue
        component = set()
        stack = [root]
        assigned.add(root)
        while stack:
            node = stack.pop()
            component.add(node)
            for neighbor in reversed(ordered_reverse[node]):
                if neighbor not in assigned:
                    assigned.add(neighbor)
                    stack.append(neighbor)
        if len(component) > 1 or any(node in self_loops for node in component):
            components.append(frozenset(component))
    return tuple(sorted(components, key=lambda item: tuple(sorted(item))))


def _canonical_cycle_path(
    component: frozenset,
    edges: Tuple[CompiledEdge, ...],
) -> Tuple[str, ...]:
    adjacency: Dict[str, set] = {}
    for edge in edges:
        if edge.target_id is None:
            continue
        if edge.source_id in component and edge.target_id in component:
            adjacency.setdefault(edge.source_id, set()).add(edge.target_id)
    start = min(component)
    if start in adjacency.get(start, set()):
        return (start, start)

    ordered = {
        node: tuple(sorted(adjacency.get(node, ()))) for node in component}
    path = [start]
    in_path = {start}
    stack = [(start, 0)]
    while stack:
        node, index = stack[-1]
        neighbors = ordered[node]
        if index >= len(neighbors):
            stack.pop()
            in_path.remove(path.pop())
            continue
        neighbor = neighbors[index]
        stack[-1] = (node, index + 1)
        if neighbor == start:
            return tuple(path + [start])
        if neighbor in in_path:
            continue
        path.append(neighbor)
        in_path.add(neighbor)
        stack.append((neighbor, 0))
    # Strong connectivity guarantees a cycle through start.  This fallback is
    # defensive and deterministic if an inconsistent edge set reaches here.
    return tuple(sorted(component)) + (min(component),)


def source_state_signature(
    paths: Sequence[str],
    *,
    extra_schema_files: Sequence[str] = (),
) -> str:
    """Hash path, stat, and content state for safe in-process reloads.

    mtime and size remain useful invalidation hints, while the content digest
    detects same-size changes whose timestamp was restored.  File membership
    and root-relative labels detect additions, deletions, and renames.
    """
    normalized = _normalized_paths(paths)
    files = _source_input_files(normalized, extra_schema_files)
    entries = []
    roots = _roots_for_paths(normalized)
    for path in sorted(files, key=_path_sort_key):
        label = _fingerprint_label(path, roots)
        try:
            stat = os.stat(path)
            with open(path, "rb") as handle:
                digest = hashlib.sha256(handle.read()).hexdigest()
            entries.append({
                "path": label,
                "mtime_ns": stat.st_mtime_ns,
                "size": stat.st_size,
                "sha256": digest,
            })
        except OSError:
            entries.append({"path": label, "missing": True})
    return _digest_json({
        "compiler_contract": COMPILER_CONTRACT_VERSION,
        "entries": entries,
    })


def _compiled_fingerprint(workspace: Workspace, paths: Sequence[str]) -> str:
    compiler_contract = (
        EXPLICIT_EDGE_COMPILER_CONTRACT_VERSION
        if workspace.explicit_edges_enabled
        else COMPILER_CONTRACT_VERSION
    )
    if paths:
        # Reuse the existing audited content fingerprint, then bind it to the
        # compiler contract version.  Paths are normalized and sorted first so
        # caller input order cannot change the compiled identity.
        from memdsl.review import workspace_fingerprint

        source_digest = workspace_fingerprint(paths, workspace=workspace)
        payload = {
            "compiler_contract": compiler_contract,
            "workspace_fingerprint": source_digest,
        }
    else:
        payload = {
            "compiler_contract": compiler_contract,
            "workspace": _in_memory_workspace_payload(workspace),
        }
    return _digest_json(payload)


def _in_memory_workspace_payload(workspace: Workspace) -> dict:
    declarations = []
    for declaration in workspace.declarations:
        declarations.append({
            "kind": declaration.kind,
            "name": declaration.name,
            "module": declaration.module,
            "uses": list(declaration.uses),
            "module_statements": list(declaration.module_statements),
            "file": str(declaration.file).replace("\\", "/"),
            "line": declaration.line,
            "fields": _json_safe(declaration.fields),
        })
    declarations.sort(key=lambda item: (
        item["kind"],
        item["name"],
        item["file"],
        item["line"],
        json.dumps(item["fields"], ensure_ascii=False, sort_keys=True),
    ))
    descriptors = []
    for descriptor in workspace.registry.descriptors():
        item = descriptor.as_dict()
        item.pop("source", None)
        descriptors.append(_json_safe(item))
    descriptors.sort(key=lambda item: str(item.get("name", "")))
    edge_relations = []
    for descriptor in workspace.registry.edge_relation_descriptors():
        item = descriptor.as_dict()
        item.pop("source", None)
        edge_relations.append(_json_safe(item))
    edge_relations.sort(key=lambda item: str(item.get("name", "")))
    source_edges = [
        {
            "kind": edge.kind,
            "name": edge.name,
            "module": edge.module,
            "file": str(edge.file).replace("\\", "/"),
            "line": edge.line,
            "fields": _json_safe(edge.fields),
        }
        for edge in workspace.explicit_edges
    ]
    source_edges.sort(key=lambda item: (
        item["name"], item["file"], item["line"],
        json.dumps(item["fields"], ensure_ascii=False, sort_keys=True),
    ))
    edge_events = [
        {
            "kind": event.kind,
            "name": event.name,
            "module": event.module,
            "file": str(event.file).replace("\\", "/"),
            "line": event.line,
            "fields": _json_safe(event.fields),
        }
        for event in workspace.edge_events
    ]
    edge_events.sort(key=lambda item: (
        item["name"], item["file"], item["line"],
        json.dumps(item["fields"], ensure_ascii=False, sort_keys=True),
    ))
    documents = []
    declaration_files = {str(item.file) for item in workspace.declarations}
    for document in workspace.documents:
        # Declaration-backed document semantics are already represented on
        # each declaration.  Retain only empty source documents here so a
        # module/use header awaiting an approved append still affects the
        # in-memory fingerprint without breaking reversed-declaration parity.
        if str(document.file) in declaration_files:
            continue
        documents.append({
            "file": str(document.file).replace("\\", "/"),
            "module": document.module,
            "module_statements": [
                {"value": item.value, "line": item.line}
                for item in document.module_statements
            ],
            "uses": [
                {"value": item.value, "line": item.line}
                for item in document.use_statements
            ],
        })
    documents.sort(key=lambda item: (
        item["file"],
        str(item["module"] or ""),
        json.dumps(item, ensure_ascii=False, sort_keys=True),
    ))
    payload = {
        "workspace_schema_version": workspace.schema_version,
        "linking_visibility": workspace.linking_visibility,
        "enforcement_mode": workspace.enforcement_mode,
        "declarations": declarations,
        "documents": documents,
        "types": descriptors,
    }
    if workspace.explicit_edges_enabled:
        payload.update({
            "explicit_edges_enabled": True,
            "explicit_edges": source_edges,
            "edge_events": edge_events,
            "edge_relations": edge_relations,
        })
    return payload


def _source_input_files(
    paths: Sequence[str],
    extra_schema_files: Sequence[str],
) -> set:
    files = set()
    manifests = set()
    for path in paths:
        if os.path.isdir(path):
            for root, dirs, names in os.walk(path):
                dirs[:] = sorted(dirs)
                for name in sorted(names):
                    candidate = os.path.realpath(os.path.join(root, name))
                    if name.endswith(".mem"):
                        files.add(candidate)
            manifest = os.path.join(path, "memdsl.json")
        else:
            if path.endswith(".mem"):
                files.add(os.path.realpath(path))
            manifest = os.path.join(os.path.dirname(path), "memdsl.json")
        if os.path.isfile(manifest):
            manifest = os.path.realpath(manifest)
            files.add(manifest)
            manifests.add(manifest)

    for manifest in manifests:
        try:
            with open(manifest, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        schemas = payload.get("schemas", []) if isinstance(payload, dict) else []
        if isinstance(schemas, list):
            for schema in schemas:
                if isinstance(schema, str) and schema.strip():
                    files.add(os.path.realpath(os.path.join(
                        os.path.dirname(manifest), schema)))
    for schema in extra_schema_files:
        if str(schema).strip():
            files.add(os.path.realpath(str(schema)))
    return files


def _normalized_paths(paths: Iterable[Union[str, os.PathLike]]) -> Tuple[str, ...]:
    unique = {}
    for raw in paths:
        path = os.path.abspath(os.fspath(raw))
        unique.setdefault(os.path.normcase(path), path)
    return tuple(unique[key] for key in sorted(unique))


def _roots_for_paths(paths: Sequence[str]) -> Tuple[str, ...]:
    roots = {
        os.path.normcase(os.path.realpath(
            path if os.path.isdir(path) else os.path.dirname(path)
        )): os.path.realpath(
            path if os.path.isdir(path) else os.path.dirname(path)
        )
        for path in paths
    }
    return tuple(roots[key] for key in sorted(roots))


def _fingerprint_label(path: str, roots: Sequence[str]) -> str:
    real = os.path.realpath(path)
    for index, root in enumerate(roots):
        try:
            if os.path.commonpath([real, root]) != root:
                continue
        except ValueError:
            continue
        relative = os.path.relpath(real, root).replace(os.sep, "/")
        return f"root-{index}/{relative}"
    location = hashlib.sha256(
        os.path.normcase(real).encode("utf-8")).hexdigest()
    return f"external-schema/{location}"


def _append(index: Dict[str, list], key: str, value) -> None:
    index.setdefault(key, []).append(value)


def _freeze_declaration_index(index: Dict[str, list]) -> DeclarationIndex:
    return MappingProxyType({
        key: tuple(sorted(values, key=_declaration_sort_key))
        for key, values in sorted(index.items())
    })


def _freeze_edge_index(
    index: Dict[str, list],
    *,
    preserve_input_order: bool = False,
) -> EdgeIndex:
    return MappingProxyType({
        key: tuple(values if preserve_input_order else sorted(values, key=_edge_sort_key))
        for key, values in sorted(index.items())
    })


def _freeze_explicit_edge_index(index: Dict[str, list]) -> ExplicitEdgeIndex:
    return MappingProxyType({
        key: tuple(sorted(values, key=_compiled_explicit_edge_sort_key))
        for key, values in sorted(index.items())
    })


def _declaration_sort_key(declaration: Declaration) -> tuple:
    file_name = str(declaration.file)
    return (
        declaration.id,
        file_name.startswith("<"),
        os.path.normcase(file_name),
        declaration.line,
        _digest_json(_json_safe(declaration.fields)),
    )


def _edge_sort_key(edge: CompiledEdge) -> tuple:
    return (
        edge.source_id,
        os.path.normcase(str(edge.file)),
        edge.line,
        edge.relation,
        edge.target_id or edge.target_ref,
        edge.ordinal,
        edge.edge_id,
    )


def _compiled_explicit_edge_sort_key(edge: CompiledExplicitEdge) -> tuple:
    return (
        edge.source_id or edge.source_ref,
        edge.relation,
        edge.target_id or edge.target_ref,
        edge.edge_id,
    )


def _source_item_sort_key(item) -> tuple:
    return (
        os.path.normcase(str(item.file)),
        str(item.file),
        item.line,
        item.id,
        _digest_json(_json_safe(item.fields)),
    )


def _edge_event_sort_key(event: EdgeLifecycleEvent) -> tuple:
    return (
        event.event_at,
        event.id,
        os.path.normcase(str(event.file)),
        str(event.file),
        event.line,
    )


def _compiled_edge_event_sort_key(event: CompiledEdgeLifecycleEvent) -> tuple:
    return (
        event.event_at,
        event.event_id,
        os.path.normcase(str(event.file)),
        str(event.file),
        event.line,
    )


def _use_sort_key(use: UseResolution) -> tuple:
    return (
        os.path.normcase(str(use.file)),
        str(use.file),
        use.line,
        use.target,
        use.status,
        use.target_kind,
    )


def _diagnostic_sort_key(diagnostic: CompilationDiagnostic) -> tuple:
    return (
        os.path.normcase(str(diagnostic.file)),
        str(diagnostic.file),
        diagnostic.line,
        diagnostic.code,
        diagnostic.decl_id or "",
        diagnostic.message,
    )


def _edge_id(
    source: Declaration,
    relation: str,
    target_ref: str,
    ordinal: int,
    source_occurrence: int,
) -> str:
    digest = _digest_json({
        "source_id": source.id,
        "file": str(source.file).replace("\\", "/"),
        "line": source.line,
        "relation": relation,
        "target_ref": target_ref,
        "ordinal": ordinal,
        "source_occurrence": source_occurrence,
    })
    return f"edge:{digest[:24]}"


def _path_sort_key(path: str) -> tuple:
    return os.path.normcase(path), path


def _json_safe(value):
    if isinstance(value, dict):
        return {
            str(key): _json_safe(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _digest_json(value) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
