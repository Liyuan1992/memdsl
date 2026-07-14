"""Internal deterministic workspace compilation through Phase 3.

This module is deliberately not re-exported from :mod:`memdsl`.  It provides
the indexed, rebuildable representation used by the existing v0.6 read
surfaces without creating a public ``CompiledWorkspace`` API commitment yet.
Source declarations remain authoritative; every object here can be discarded
and rebuilt from a :class:`memdsl.model.Workspace`.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Dict, Iterable, Mapping, Optional, Sequence, Tuple, Union

from memdsl.lexical import query_terms
from memdsl.model import Declaration, EXCLUDED_STATUSES, RELATION_FIELDS, Workspace


COMPILER_CONTRACT_VERSION = "memdsl.compiler.phase3.v1"


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


DeclarationIndex = Mapping[str, Tuple[Declaration, ...]]
EdgeIndex = Mapping[str, Tuple[CompiledEdge, ...]]


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
    diagnostics: Tuple[CompilationDiagnostic, ...]
    revision_cycle_edge_ids: frozenset
    authoritative_supersedes: Tuple[CompiledEdge, ...]
    _legacy_incoming: EdgeIndex = field(repr=False, compare=False)
    _first_by_id: Mapping[str, Declaration] = field(repr=False, compare=False)
    _first_by_name: Mapping[str, Declaration] = field(repr=False, compare=False)
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
                    target_id=resolution.target_id,
                    status=resolution.status,
                    file=declaration.file,
                    line=declaration.line,
                    ordinal=ordinal,
                    candidate_ids=resolution.candidate_ids,
                )
                _append(outgoing, declaration.id, edge)
                if edge.target_id is not None:
                    _append(incoming, edge.target_id, edge)

                # Preserve the v0.6 explain projection without rescanning all
                # declarations.  Full ids match exactly; bare names fan out to
                # every legacy name match even when compiler linking marks the
                # reference ambiguous.
                legacy_targets = (
                    frozen_occurrences.get(target_ref, ())
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
    diagnostics = _compile_diagnostics(
        declarations=declarations,
        occurrences_by_id=frozen_occurrences,
        resolved_by_id=resolved_by_id,
        edges=all_edges,
        revision_edges=revision_edges,
        revision_components=revision_components,
        authoritative_supersedes=authoritative_supersedes,
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
        diagnostics=diagnostics,
        revision_cycle_edge_ids=revision_cycle_edge_ids,
        authoritative_supersedes=authoritative_supersedes,
        _legacy_incoming=_freeze_edge_index(
            legacy_incoming, preserve_input_order=True),
        _first_by_id=MappingProxyType(dict(first_by_id)),
        _first_by_name=MappingProxyType(dict(first_by_name)),
        workspace=workspace,
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
) -> Tuple[CompilationDiagnostic, ...]:
    diagnostics = []

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
    if paths:
        # Reuse the existing audited content fingerprint, then bind it to the
        # compiler contract version.  Paths are normalized and sorted first so
        # caller input order cannot change the compiled identity.
        from memdsl.review import workspace_fingerprint

        source_digest = workspace_fingerprint(paths, workspace=workspace)
        payload = {
            "compiler_contract": COMPILER_CONTRACT_VERSION,
            "workspace_fingerprint": source_digest,
        }
    else:
        payload = {
            "compiler_contract": COMPILER_CONTRACT_VERSION,
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
    return {"declarations": declarations, "types": descriptors}


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
