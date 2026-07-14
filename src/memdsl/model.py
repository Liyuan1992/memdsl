"""Domain-neutral memory records, symbol table, and workspace loading."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple, Union

from memdsl.parser import (
    EDGE_EVENT_KINDS,
    EXPLICIT_EDGE_KINDS,
    Document,
    parse_file,
)
from memdsl.schema import (
    SchemaError,
    WORKSPACE_SCHEMA_VERSION,
    TypeDescriptor,
    TypeRegistry,
    registry_for_paths,
)

#: Relation field names recognized inside a `relations { ... }` block
#: or as top-level fields.
RELATION_FIELDS = {
    "supports", "refines", "depends_on", "part_of", "supersedes",
    "conflicts_with", "derived_from", "related_to", "revision_of",
}

ACTIVE_STATUSES = {"active"}
EXCLUDED_STATUSES = {"superseded", "retracted", "archived"}
EDGE_INACTIVE_STATUSES = {
    "candidate", "disputed", "quarantined", "retracted", "superseded",
}
EDGE_LIFECYCLE_ACTIONS = frozenset({"confirm", "dispute", "retract", "supersede"})


@dataclass
class Declaration:
    kind: str
    name: str
    fields: dict
    file: str
    line: int
    module: Optional[str] = None
    uses: Tuple[str, ...] = ()
    module_statements: Tuple[str, ...] = ()
    type_descriptor: Optional[TypeDescriptor] = field(default=None, repr=False)

    @property
    def id(self) -> str:
        return f"{self.kind}:{self.name}"

    @property
    def type_name(self) -> str:
        return self.kind

    def field(self, name: str, default=None):
        if name in self.fields:
            return self.fields[name]
        if self.type_descriptor and name in self.type_descriptor.defaults:
            return self.type_descriptor.defaults[name]
        return default

    @property
    def status(self) -> str:
        lifecycle = self.fields.get("lifecycle")
        if isinstance(lifecycle, dict) and "status" in lifecycle:
            return str(lifecycle["status"])
        return str(self.field("status", "active"))

    @property
    def force(self) -> Optional[str]:
        v = self.field("force")
        return str(v) if v is not None else None

    @property
    def subject(self) -> Optional[str]:
        v = self.field("subject")
        return str(v) if v is not None else None

    @property
    def scope(self) -> Optional[str]:
        v = self.field("scope")
        return str(v) if v is not None else None

    @property
    def confidence(self):
        return self.field("confidence")

    @property
    def lifecycle(self) -> dict:
        nested = self.fields.get("lifecycle")
        result = dict(nested) if isinstance(nested, dict) else {}
        for key in ("status", "as_of", "valid_until"):
            if key not in result and self.field(key) is not None:
                result[key] = self.field(key)
        if "status" not in result:
            result["status"] = "active"
        return result

    @property
    def access_policy(self) -> dict:
        value = self.field("access_policy", self.field("access"))
        return dict(value) if isinstance(value, dict) else {}

    @property
    def runtime_role(self) -> str:
        if self.type_descriptor is None:
            return "unknown"
        return self.type_descriptor.role_for(self.fields)

    @property
    def capabilities(self) -> frozenset:
        if self.type_descriptor is None:
            return frozenset()
        return self.type_descriptor.capabilities

    def has_capability(self, name: str) -> bool:
        return name in self.capabilities

    @property
    def claim_text(self) -> str:
        """The primary human-readable statement of this declaration."""
        if self.type_descriptor is not None:
            claim = self.type_descriptor.claim_for(self.fields)
            if claim:
                return claim
        for key in ("claim", "rule", "decision", "pattern", "summary"):
            v = self.fields.get(key)
            if isinstance(v, str):
                return v
        return ""

    @property
    def evidence(self) -> Optional[dict]:
        v = self.field("evidence")
        return v if isinstance(v, dict) else None

    def relations(self) -> Dict[str, List[str]]:
        """All relations declared on this declaration, normalized to lists."""
        out: Dict[str, List[str]] = {}
        sources = [self.fields]
        rel_block = self.field("relations")
        if isinstance(rel_block, dict):
            sources.append(rel_block)
        for src in sources:
            for key, value in src.items():
                if key in RELATION_FIELDS:
                    targets = value if isinstance(value, list) else [value]
                    out.setdefault(key, []).extend(str(t) for t in targets)
        return out

    def searchable_text(self) -> str:
        parts = [self.name.replace(".", " "), self.claim_text]
        if self.subject:
            parts.append(self.subject.replace(".", " "))
        for key in ("aliases", "tags", "facets", "exceptions", "canonical_name", "about"):
            v = self.fields.get(key)
            if isinstance(v, list):
                parts.extend(str(x) for x in v)
            elif isinstance(v, str):
                parts.append(v)
        if self.type_descriptor:
            for key in self.type_descriptor.search_fields:
                value = self.field(key)
                if isinstance(value, list):
                    parts.extend(str(item) for item in value)
                elif isinstance(value, str):
                    parts.append(value)
        return " ".join(parts).lower()


@dataclass
class ExplicitEdge:
    """A stable, evidence-bearing relation between two declaration ids.

    ``relation_edge`` and ``explicit_edge`` are accepted source spellings, but
    both compile to the canonical identity ``relation_edge:<name>``.
    """

    name: str
    fields: dict
    file: str
    line: int
    module: Optional[str] = None
    source_kind: str = "relation_edge"

    @property
    def id(self) -> str:
        return f"relation_edge:{self.name}"

    @property
    def kind(self) -> str:
        return "relation_edge"

    @property
    def source_ref(self) -> str:
        return str(self.fields.get("source", ""))

    @property
    def declared_by_ref(self) -> str:
        return str(self.fields.get("declared_by", ""))

    @property
    def target_ref(self) -> str:
        return str(self.fields.get("target", ""))

    @property
    def relation(self) -> str:
        return str(self.fields.get("relation", ""))

    @property
    def evidence(self) -> Optional[dict]:
        value = self.fields.get("evidence")
        return value if isinstance(value, dict) else None

    @property
    def lifecycle(self) -> dict:
        value = self.fields.get("lifecycle")
        result = dict(value) if isinstance(value, dict) else {}
        if "status" not in result:
            result["status"] = str(self.fields.get("status", "candidate"))
        return result

    @property
    def status(self) -> str:
        return str(self.lifecycle.get("status", "candidate"))

    @property
    def runtime_role(self) -> str:
        return "edge"

    @property
    def capabilities(self) -> frozenset:
        return frozenset({"explicit_edge", "relation_edge"})

    def has_capability(self, name: str) -> bool:
        return name in self.capabilities

    @property
    def scope(self) -> Optional[str]:
        value = self.fields.get("scope")
        return str(value) if value is not None else None

    @property
    def force(self) -> Optional[str]:
        return None

    @property
    def access_policy(self) -> dict:
        value = self.fields.get("access_policy", self.fields.get("access"))
        return dict(value) if isinstance(value, dict) else {}

    @property
    def subject(self) -> Optional[str]:
        return None

    def relations(self) -> Dict[str, List[str]]:
        return {}


@dataclass
class EdgeLifecycleEvent:
    """Append-only confirm/dispute/retract/supersede event for one Edge."""

    name: str
    fields: dict
    file: str
    line: int
    module: Optional[str] = None
    source_kind: str = "relation_edge_event"

    @property
    def id(self) -> str:
        return f"relation_edge_event:{self.name}"

    @property
    def kind(self) -> str:
        return "relation_edge_event"

    @property
    def edge_ref(self) -> str:
        return str(self.fields.get("edge", ""))

    @property
    def action(self) -> str:
        return str(self.fields.get("action", ""))

    @property
    def event_at(self) -> str:
        return str(self.fields.get("event_at", ""))

    @property
    def replacement_ref(self) -> str:
        return str(self.fields.get("replacement", ""))

    @property
    def evidence(self) -> Optional[dict]:
        value = self.fields.get("evidence")
        return value if isinstance(value, dict) else None

    @property
    def lifecycle(self) -> dict:
        value = self.fields.get("lifecycle")
        result = dict(value) if isinstance(value, dict) else {}
        if "status" not in result:
            result["status"] = str(self.fields.get("status", "active"))
        return result

    @property
    def status(self) -> str:
        return str(self.lifecycle.get("status", "active"))

    @property
    def runtime_role(self) -> str:
        return "edge_event"

    @property
    def capabilities(self) -> frozenset:
        return frozenset({"explicit_edge", "relation_edge", "edge_lifecycle"})

    def has_capability(self, name: str) -> bool:
        return name in self.capabilities

    @property
    def scope(self) -> Optional[str]:
        return None

    @property
    def force(self) -> Optional[str]:
        return None

    @property
    def access_policy(self) -> dict:
        return {}

    @property
    def subject(self) -> Optional[str]:
        return None

    def relations(self) -> Dict[str, List[str]]:
        return {}


ReviewableSource = Union[Declaration, ExplicitEdge, EdgeLifecycleEvent]


@dataclass
class Workspace:
    declarations: List[Declaration] = field(default_factory=list)
    explicit_edges: List[ExplicitEdge] = field(default_factory=list)
    edge_events: List[EdgeLifecycleEvent] = field(default_factory=list)
    files: List[str] = field(default_factory=list)
    registry: TypeRegistry = field(default_factory=TypeRegistry.standard, repr=False)
    documents: List[Document] = field(default_factory=list, repr=False)
    schema_version: str = WORKSPACE_SCHEMA_VERSION
    linking_visibility: str = "legacy"
    enforcement_mode: str = "legacy"
    explicit_edges_enabled: bool = False

    # ---- construction ----

    @classmethod
    def load(
        cls,
        paths: Iterable[str],
        *,
        registry: Optional[TypeRegistry] = None,
    ) -> "Workspace":
        """Load one or more `.mem` files or directories (recursive)."""
        # Path argument order and filesystem traversal order are not semantic.
        # Normalize both so every path-backed compile sees the same source
        # occurrence order on Windows, POSIX, and reversed caller input.
        path_list = sorted(
            [str(path) for path in paths],
            key=lambda item: (
                os.path.normcase(os.path.abspath(item)),
                os.path.abspath(item),
                item,
            ),
        )
        resolved_registry = registry or registry_for_paths(path_list)
        ws = cls(
            registry=resolved_registry,
            schema_version=resolved_registry.workspace_schema_version,
            linking_visibility=resolved_registry.linking_visibility,
            enforcement_mode=resolved_registry.enforcement_mode,
            explicit_edges_enabled=resolved_registry.explicit_edges_enabled,
        )
        for path in path_list:
            if os.path.isdir(path):
                for root, dirs, names in os.walk(path):
                    dirs[:] = sorted(dirs)
                    for name in sorted(names):
                        if name.endswith(".mem"):
                            ws.add_document(parse_file(os.path.join(root, name)))
            else:
                ws.add_document(parse_file(path))
        return ws

    def add_document(self, doc: Document) -> None:
        if (
            (doc.explicit_edges or doc.edge_events)
            and not self.explicit_edges_enabled
        ):
            raise SchemaError(
                "first-class explicit Edge syntax requires memdsl.workspace.v3 "
                "with features.explicit_edges='experimental-v1'")
        self.documents.append(doc)
        self.files.append(doc.file)
        module_statements = tuple(
            statement.value for statement in doc.module_statements)
        for raw in doc.declarations:
            self.declarations.append(
                Declaration(kind=raw.kind, name=raw.name, fields=raw.fields,
                            file=raw.file, line=raw.line, module=raw.module,
                            uses=tuple(doc.uses),
                            module_statements=module_statements,
                            type_descriptor=self.registry.resolve(raw.kind))
            )
        for raw in doc.explicit_edges:
            self.explicit_edges.append(ExplicitEdge(
                name=raw.name,
                fields=raw.fields,
                file=raw.file,
                line=raw.line,
                module=raw.module,
                source_kind=raw.kind,
            ))
        for raw in doc.edge_events:
            self.edge_events.append(EdgeLifecycleEvent(
                name=raw.name,
                fields=raw.fields,
                file=raw.file,
                line=raw.line,
                module=raw.module,
                source_kind=raw.kind,
            ))

    # ---- lookups ----

    def by_id(self, decl_id: str) -> Optional[Declaration]:
        for d in self.declarations:
            if d.id == decl_id or d.name == decl_id:
                return d
        return None

    def edge_by_id(self, edge_id: str) -> Optional[ExplicitEdge]:
        reference = str(edge_id or "")
        canonical = (
            reference
            if reference.startswith("relation_edge:")
            else f"relation_edge:{reference.split(':', 1)[-1]}"
        )
        matches = [item for item in self.explicit_edges if item.id == canonical]
        return matches[0] if len(matches) == 1 else None

    def reviewable_sources(self) -> List[ReviewableSource]:
        return list(self.declarations) + list(self.explicit_edges) + list(self.edge_events)

    def entities(self) -> List[Declaration]:
        return [d for d in self.declarations if d.runtime_role == "symbol"]

    def known_names(self) -> set:
        names = set()
        for d in self.declarations:
            names.add(d.name)
            names.add(d.id)
        return names

    def known_symbols(self) -> set:
        """Symbol names plus their canonical names."""
        symbols = set()
        for e in self.entities():
            symbols.add(e.name)
            cn = e.fields.get("canonical_name")
            if isinstance(cn, str):
                symbols.add(cn)
        return symbols

    def alias_map(self) -> Dict[str, List[str]]:
        """Lowercased alias -> list of canonical symbols it may refer to."""
        amap: Dict[str, List[str]] = {}
        for e in self.entities():
            aliases = e.fields.get("aliases", [])
            if isinstance(aliases, list):
                for a in aliases:
                    amap.setdefault(str(a).lower(), []).append(e.name)
        return amap

    def resolve_alias(self, text: str) -> List[str]:
        """Resolve a natural-language mention to candidate symbols."""
        return self.alias_map().get(text.lower(), [])

    def active(self) -> List[Declaration]:
        return [d for d in self.declarations if d.status not in EXCLUDED_STATUSES]

    def superseded_ids(self) -> set:
        """Raw declared supersede target references, without authority rules.

        Read and enforcement surfaces must use ``memdsl.authority`` instead;
        this compatibility helper intentionally preserves source observation.
        """
        out = set()
        for d in self.declarations:
            for target in d.relations().get("supersedes", []):
                out.add(target)
        return out
