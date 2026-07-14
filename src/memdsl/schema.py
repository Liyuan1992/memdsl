"""Extensible memory type schemas for memdsl.

The core declaration envelope is domain-neutral.  Domain schemas define
memory types and compile them to a small set of stable runtime roles used by
querying and compliance.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


RUNTIME_ROLES = frozenset({
    "symbol", "constraint", "guidance", "assertion", "question",
})
RESERVED_EDGE_KINDS = frozenset({
    "relation_edge", "explicit_edge", "relation_edge_event", "explicit_edge_event",
})
RESERVED_EDGE_CAPABILITIES = frozenset({
    "relation_edge", "explicit_edge", "relation_edge_event",
    "explicit_edge_event", "edge_lifecycle",
})
EDGE_RELATION_STABILITIES = frozenset({"stable", "experimental", "extension"})

UNIVERSAL_FIELDS = frozenset({
    "subject", "claim", "evidence", "scope", "confidence", "lifecycle",
    "access_policy", "access", "relations", "status", "force", "as_of",
    "valid_until", "tags", "facets", "exceptions", "guard",
})

WORKSPACE_MANIFEST = "memdsl.json"
WORKSPACE_SCHEMA_VERSION = "memdsl.workspace.v1"
WORKSPACE_SCHEMA_VERSION_V2 = "memdsl.workspace.v2"
WORKSPACE_SCHEMA_VERSION_V3 = "memdsl.workspace.v3"
EXPLICIT_EDGES_FEATURE = "experimental-v1"
WORKSPACE_SCHEMA_VERSIONS = frozenset({
    WORKSPACE_SCHEMA_VERSION,
    WORKSPACE_SCHEMA_VERSION_V2,
    WORKSPACE_SCHEMA_VERSION_V3,
})
LINKING_VISIBILITIES = frozenset({"report", "strict"})
ENFORCEMENT_MODES = frozenset({"report", "quarantine", "strict"})


class SchemaError(ValueError):
    """Raised when a workspace manifest or memory type schema is invalid."""


def _strings(value, field_name: str) -> Tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise SchemaError(f"{field_name} must be a list of strings")
    if any(not isinstance(item, str) for item in value):
        raise SchemaError(f"{field_name} must contain only strings")
    result = tuple(item.strip() for item in value)
    if any(not item for item in result):
        raise SchemaError(f"{field_name} contains an empty value")
    return result


def _string_mapping(value, field_name: str) -> Dict[str, str]:
    if not isinstance(value, dict):
        raise SchemaError(f"{field_name} must be an object of string values")
    if any(not isinstance(key, str) or not isinstance(item, str)
           for key, item in value.items()):
        raise SchemaError(f"{field_name} must contain only string keys and values")
    result = {key.strip(): item.strip() for key, item in value.items()}
    if any(not key or not item for key, item in result.items()):
        raise SchemaError(f"{field_name} contains an empty key or value")
    return result


@dataclass(frozen=True)
class TypeDescriptor:
    """Declarative behavior contract for one domain memory type."""

    name: str
    runtime_role: str
    required_fields: Tuple[str, ...] = ()
    optional_fields: Tuple[str, ...] = ()
    claim_fields: Tuple[str, ...] = ("claim",)
    search_fields: Tuple[str, ...] = ()
    capabilities: frozenset = frozenset()
    defaults: Mapping[str, object] = field(default_factory=dict)
    allowed_forces: Tuple[str, ...] = ()
    role_field: str = ""
    role_map: Mapping[str, str] = field(default_factory=dict)
    diagnostic_codes: Mapping[str, str] = field(default_factory=dict)
    allow_extra_fields: bool = True
    schema_name: str = ""
    schema_version: str = ""
    source: str = "<builtin>"

    def __post_init__(self) -> None:
        if not str(self.name or "").strip():
            raise SchemaError("memory type name cannot be empty")
        if not isinstance(self.runtime_role, str):
            raise SchemaError(f"type {self.name!r} runtime_role must be a string")
        if any(not isinstance(key, str) or not isinstance(value, str)
               for key, value in self.role_map.items()):
            raise SchemaError(
                f"type {self.name!r} role_map must contain string keys and values")
        roles = {self.runtime_role} | set(self.role_map.values())
        unknown = sorted(roles - RUNTIME_ROLES)
        if unknown:
            raise SchemaError(
                f"type {self.name!r} uses unknown runtime role(s): {', '.join(unknown)}")
        if self.role_map and not self.role_field:
            raise SchemaError(
                f"type {self.name!r} defines role_map without role_field")
        if self.name in RESERVED_EDGE_KINDS:
            raise SchemaError(
                f"type name {self.name!r} is reserved for the core explicit Edge contract")
        if (
            self.capabilities & RESERVED_EDGE_CAPABILITIES
            and "auto_approvable" in self.capabilities
        ):
            raise SchemaError(
                f"type {self.name!r} cannot combine explicit Edge capability "
                "with auto_approvable")

    def role_for(self, fields: Mapping[str, object]) -> str:
        if self.role_field:
            value = fields.get(self.role_field, self.defaults.get(self.role_field))
            mapped = self.role_map.get(str(value)) if value is not None else None
            if mapped:
                return mapped
        return self.runtime_role

    def claim_for(self, fields: Mapping[str, object]) -> str:
        for key in self.claim_fields:
            value = fields.get(key, self.defaults.get(key))
            if isinstance(value, str):
                return value
        return ""

    def has_capability(self, name: str) -> bool:
        return name in self.capabilities

    @property
    def allowed_fields(self) -> frozenset:
        referenced = (
            set(self.required_fields)
            | set(self.optional_fields)
            | set(self.claim_fields)
            | set(self.search_fields)
            | set(self.defaults)
        )
        if self.role_field:
            referenced.add(self.role_field)
        return UNIVERSAL_FIELDS | frozenset(referenced)

    def as_dict(self) -> dict:
        """Serializable discovery contract for CLI and MCP clients."""
        return {
            "name": self.name,
            "runtime_role": self.runtime_role,
            "required_fields": list(self.required_fields),
            "optional_fields": list(self.optional_fields),
            "claim_fields": list(self.claim_fields),
            "search_fields": list(self.search_fields),
            "capabilities": sorted(self.capabilities),
            "defaults": dict(self.defaults),
            "allowed_forces": list(self.allowed_forces),
            "role_field": self.role_field,
            "role_map": dict(self.role_map),
            "allow_extra_fields": self.allow_extra_fields,
            "schema": self.schema_name,
            "schema_version": self.schema_version,
            "source": self.source,
        }


@dataclass(frozen=True)
class EdgeRelationDescriptor:
    """Public structural vocabulary entry for one explicit Edge relation."""

    name: str
    stability: str = "extension"
    description: str = ""
    source: str = "<workspace>"

    def __post_init__(self) -> None:
        if not str(self.name or "").strip():
            raise SchemaError("edge relation name cannot be empty")
        if self.stability not in EDGE_RELATION_STABILITIES:
            raise SchemaError(
                f"edge relation {self.name!r} stability must be one of "
                f"{sorted(EDGE_RELATION_STABILITIES)!r}")

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "stability": self.stability,
            "description": self.description,
            "source": self.source,
        }


def standard_edge_relation_descriptors() -> List[EdgeRelationDescriptor]:
    """Pilot-supported minimum; lower-evidence relations remain extensions."""
    descriptions = {
        "supports": "Source evidence strengthens or corroborates the target.",
        "depends_on": "The source depends on the target remaining available or true.",
        "supersedes": "The source Edge records replacement intent without Phase 6 node authority.",
        "contradicts": "The source and target cannot both be accepted without review.",
    }
    return [
        EdgeRelationDescriptor(
            name=name,
            stability="experimental",
            description=descriptions[name],
            source="<builtin:memdsl.explicit-edge@1>",
        )
        for name in ("supports", "depends_on", "supersedes", "contradicts")
    ]


class TypeRegistry:
    """Registry of built-in and workspace-defined memory types."""

    def __init__(self) -> None:
        self._types: Dict[str, TypeDescriptor] = {}
        self._edge_relations: Dict[str, EdgeRelationDescriptor] = {}
        self.schema_files: List[str] = []
        self.manifest_files: List[str] = []
        self.workspace_schema_version = WORKSPACE_SCHEMA_VERSION
        self.linking_visibility = "legacy"
        self.enforcement_mode = "legacy"
        self.explicit_edges_enabled = False

    def register(self, descriptor: TypeDescriptor, *, replace: bool = False) -> None:
        name = str(descriptor.name or "").strip()
        if not name:
            raise SchemaError("memory type name cannot be empty")
        if name in self._types and not replace:
            previous = self._types[name]
            if _descriptor_contract(previous) == _descriptor_contract(descriptor):
                return
            raise SchemaError(
                f"memory type {name!r} is already defined by {previous.source}")
        self._types[name] = descriptor

    def resolve(self, name: str) -> Optional[TypeDescriptor]:
        return self._types.get(str(name or ""))

    def names(self) -> List[str]:
        return sorted(self._types)

    def descriptors(self) -> List[TypeDescriptor]:
        return [self._types[name] for name in self.names()]

    def register_edge_relation(
        self, descriptor: EdgeRelationDescriptor, *, replace: bool = False,
    ) -> None:
        name = str(descriptor.name or "").strip()
        if name in self._edge_relations and not replace:
            previous = self._edge_relations[name]
            if previous == descriptor:
                return
            raise SchemaError(
                f"edge relation {name!r} is already defined by {previous.source}")
        self._edge_relations[name] = descriptor

    def resolve_edge_relation(self, name: str) -> Optional[EdgeRelationDescriptor]:
        return self._edge_relations.get(str(name or ""))

    def edge_relation_names(self) -> List[str]:
        return sorted(self._edge_relations)

    def edge_relation_descriptors(self) -> List[EdgeRelationDescriptor]:
        return [self._edge_relations[name] for name in self.edge_relation_names()]

    def load_schema(self, path: str) -> List[TypeDescriptor]:
        absolute = os.path.abspath(path)
        try:
            with open(absolute, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except json.JSONDecodeError as exc:
            raise SchemaError(f"{absolute}: invalid JSON: {exc}") from exc
        except OSError as exc:
            raise SchemaError(f"cannot read schema {absolute}: {exc}") from exc
        if not isinstance(payload, dict):
            raise SchemaError(f"{absolute}: schema root must be an object")
        raw_schema_name = payload.get("name", "")
        raw_schema_version = payload.get("version", "")
        schema_name = raw_schema_name.strip() if isinstance(raw_schema_name, str) else ""
        schema_version = (
            raw_schema_version.strip()
            if isinstance(raw_schema_version, str) else "")
        raw_types = payload.get("types")
        raw_relations = payload.get("relations", {})
        if (
            not schema_name
            or not schema_version
            or not isinstance(raw_types, dict)
            or not isinstance(raw_relations, dict)
        ):
            raise SchemaError(
                f"{absolute}: schema requires name, version, and object-valued "
                "types/relations")
        loaded: List[TypeDescriptor] = []
        for local_name, raw in raw_types.items():
            if not isinstance(raw, dict):
                raise SchemaError(f"{absolute}: type {local_name!r} must be an object")
            local = str(local_name).strip()
            if not local:
                raise SchemaError(f"{absolute}: memory type name cannot be empty")
            full_name = local if "." in local else f"{schema_name}.{local}"
            defaults = raw.get("defaults", {})
            role_map = raw.get("role_map", {})
            diagnostic_codes = raw.get("diagnostic_codes", {})
            if (not isinstance(defaults, dict)
                    or not isinstance(role_map, dict)
                    or not isinstance(diagnostic_codes, dict)):
                raise SchemaError(
                    f"{absolute}: type {full_name!r} defaults, role_map, and "
                    "diagnostic_codes must be objects")
            runtime_role = raw.get("runtime_role", "assertion")
            role_field = raw.get("role_field", "")
            allow_extra_fields = raw.get("allow_extra_fields", False)
            if not isinstance(runtime_role, str):
                raise SchemaError(f"{absolute}: {full_name}.runtime_role must be a string")
            if not isinstance(role_field, str):
                raise SchemaError(f"{absolute}: {full_name}.role_field must be a string")
            if not isinstance(allow_extra_fields, bool):
                raise SchemaError(
                    f"{absolute}: {full_name}.allow_extra_fields must be a boolean")
            descriptor = TypeDescriptor(
                name=full_name,
                runtime_role=runtime_role.strip(),
                required_fields=_strings(
                    raw.get("required_fields", []), f"{full_name}.required_fields"),
                optional_fields=_strings(
                    raw.get("optional_fields", []), f"{full_name}.optional_fields"),
                claim_fields=_strings(
                    raw.get("claim_fields", ["claim"]), f"{full_name}.claim_fields"),
                search_fields=_strings(
                    raw.get("search_fields", []), f"{full_name}.search_fields"),
                capabilities=frozenset(_strings(
                    raw.get("capabilities", []), f"{full_name}.capabilities")),
                defaults=dict(defaults),
                allowed_forces=_strings(
                    raw.get("allowed_forces", []), f"{full_name}.allowed_forces"),
                role_field=role_field.strip(),
                role_map=_string_mapping(role_map, f"{full_name}.role_map"),
                diagnostic_codes=_string_mapping(
                    diagnostic_codes, f"{full_name}.diagnostic_codes"),
                allow_extra_fields=allow_extra_fields,
                schema_name=schema_name,
                schema_version=schema_version,
                source=absolute,
            )
            self.register(descriptor)
            loaded.append(descriptor)
        for local_name, raw in raw_relations.items():
            if not isinstance(raw, dict):
                raise SchemaError(
                    f"{absolute}: relation {local_name!r} must be an object")
            local = str(local_name).strip()
            if not local:
                raise SchemaError(f"{absolute}: edge relation name cannot be empty")
            full_name = local if "." in local else f"{schema_name}.{local}"
            stability = raw.get("stability", "extension")
            description = raw.get("description", "")
            if not isinstance(stability, str) or not isinstance(description, str):
                raise SchemaError(
                    f"{absolute}: relation {full_name!r} stability and description "
                    "must be strings")
            self.register_edge_relation(EdgeRelationDescriptor(
                name=full_name,
                stability=stability.strip(),
                description=description.strip(),
                source=absolute,
            ))
        if absolute not in self.schema_files:
            self.schema_files.append(absolute)
        return loaded

    @classmethod
    def standard(cls) -> "TypeRegistry":
        registry = cls()
        for descriptor in standard_type_descriptors():
            registry.register(descriptor)
        for descriptor in standard_edge_relation_descriptors():
            registry.register_edge_relation(descriptor)
        return registry


def _standard(
    name: str,
    role: str,
    *,
    required: Sequence[str] = (),
    optional: Sequence[str] = (),
    claim_fields: Sequence[str] = ("claim",),
    capabilities: Sequence[str] = ("searchable",),
    allowed_forces: Sequence[str] = (),
    role_field: str = "",
    role_map: Optional[Mapping[str, str]] = None,
    diagnostic_codes: Optional[Mapping[str, str]] = None,
) -> TypeDescriptor:
    return TypeDescriptor(
        name=name,
        runtime_role=role,
        required_fields=tuple(required),
        optional_fields=tuple(optional),
        claim_fields=tuple(claim_fields),
        capabilities=frozenset(capabilities),
        allowed_forces=tuple(allowed_forces),
        role_field=role_field,
        role_map=dict(role_map or {}),
        diagnostic_codes=dict(diagnostic_codes or {}),
        allow_extra_fields=True,
        schema_name="memdsl.standard",
        schema_version="1",
        source="<builtin:memdsl.standard@1>",
    )


def _descriptor_contract(descriptor: TypeDescriptor) -> tuple:
    """Comparable schema contract excluding file provenance."""
    return (
        descriptor.name,
        descriptor.runtime_role,
        descriptor.required_fields,
        descriptor.optional_fields,
        descriptor.claim_fields,
        descriptor.search_fields,
        tuple(sorted(descriptor.capabilities)),
        tuple(sorted((str(k), repr(v)) for k, v in descriptor.defaults.items())),
        descriptor.allowed_forces,
        descriptor.role_field,
        tuple(sorted(descriptor.role_map.items())),
        tuple(sorted(descriptor.diagnostic_codes.items())),
        descriptor.allow_extra_fields,
        descriptor.schema_name,
        descriptor.schema_version,
    )


def standard_type_descriptors() -> List[TypeDescriptor]:
    """Backward-compatible standard type pack for pre-v0.5 workspaces."""
    evidence = ("requires_evidence", "searchable")
    return [
        _standard("entity", "symbol", capabilities=("symbol",)),
        _standard("fact", "assertion", required=("evidence",), capabilities=evidence),
        _standard(
            "preference", "assertion", required=("evidence",),
            capabilities=evidence, allowed_forces=("advisory", "strong"),
            role_field="force", role_map={"strong": "guidance"}),
        _standard(
            "boundary", "constraint", required=("evidence",),
            claim_fields=("rule", "claim"),
            capabilities=(
                "requires_evidence", "searchable", "enforceable", "guardable",
                "exceptions_recommended"),
            allowed_forces=("hard",),
            diagnostic_codes={
                "exceptions_recommended": "boundary_without_exception"}),
        _standard(
            "principle", "guidance", required=("evidence",), capabilities=evidence),
        _standard(
            "decision", "assertion", required=("evidence",),
            claim_fields=("decision", "claim"), capabilities=evidence),
        _standard(
            "state", "assertion", required=("evidence",),
            claim_fields=("claim", "summary"),
            capabilities=("requires_evidence", "searchable", "temporal"),
            diagnostic_codes={"stale": "stale_state"}),
        _standard(
            "open_issue", "question", required=("next_action",),
            capabilities=("searchable",)),
        _standard("goal", "assertion", capabilities=("searchable",)),
        _standard("relationship", "assertion", capabilities=("searchable",)),
        _standard("skill", "assertion", capabilities=("searchable",)),
        _standard("lesson", "assertion", capabilities=("searchable",)),
        _standard("behavior_event", "assertion", capabilities=("searchable",)),
        _standard("behavior_pattern", "assertion", capabilities=("searchable",)),
        _standard("habit", "assertion", capabilities=("searchable",)),
        _standard("personhood_signal", "assertion", capabilities=("searchable",)),
        _standard("counter_evidence", "assertion", capabilities=("searchable",)),
        _standard("motive_hypothesis", "assertion", capabilities=("searchable",)),
    ]


def registry_for_paths(paths: Iterable[str]) -> TypeRegistry:
    """Load the standard pack plus schemas declared by workspace manifests."""
    registry = TypeRegistry.standard()
    manifests: List[str] = []
    for raw_path in paths:
        path = os.path.abspath(str(raw_path))
        root = path if os.path.isdir(path) else os.path.dirname(path)
        manifest = os.path.join(root, WORKSPACE_MANIFEST)
        if os.path.isfile(manifest) and manifest not in manifests:
            manifests.append(manifest)
    manifest_contract: Optional[Tuple[str, str, str, bool]] = None
    for manifest in sorted(manifests):
        try:
            with open(manifest, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except json.JSONDecodeError as exc:
            raise SchemaError(f"{manifest}: invalid JSON: {exc}") from exc
        except OSError as exc:
            raise SchemaError(f"cannot read manifest {manifest}: {exc}") from exc
        if not isinstance(payload, dict):
            raise SchemaError(f"{manifest}: manifest root must be an object")
        manifest_version = payload.get("schema_version")
        if manifest_version not in WORKSPACE_SCHEMA_VERSIONS:
            raise SchemaError(
                f"{manifest}: schema_version must be one of "
                f"{sorted(WORKSPACE_SCHEMA_VERSIONS)!r}")
        if manifest_version == WORKSPACE_SCHEMA_VERSION:
            forbidden = sorted(set(payload) & {"linking", "enforcement", "features"})
            if forbidden:
                raise SchemaError(
                    f"{manifest}: memdsl.workspace.v1 cannot declare "
                    f"{', '.join(repr(item) for item in forbidden)}; use "
                    "memdsl.workspace.v2 for visibility/enforcement semantics")
            linking_visibility = "legacy"
            enforcement_mode = "legacy"
            explicit_edges_enabled = False
        else:
            allowed_fields = {
                "schema_version", "schemas", "linking", "enforcement",
            }
            if manifest_version == WORKSPACE_SCHEMA_VERSION_V3:
                allowed_fields.add("features")
            unknown = sorted(
                set(payload) - allowed_fields)
            if unknown:
                raise SchemaError(
                    f"{manifest}: {manifest_version} has unknown field(s): "
                    f"{', '.join(unknown)}")
            linking = payload.get("linking")
            if not isinstance(linking, dict):
                raise SchemaError(
                    f"{manifest}: memdsl.workspace.v2 requires object-valued linking")
            unknown_linking = sorted(set(linking) - {"visibility"})
            if unknown_linking:
                raise SchemaError(
                    f"{manifest}: linking has unknown field(s): "
                    f"{', '.join(unknown_linking)}")
            linking_visibility = linking.get("visibility")
            if linking_visibility not in LINKING_VISIBILITIES:
                raise SchemaError(
                    f"{manifest}: linking.visibility must be 'report' or 'strict'")
            enforcement = payload.get("enforcement", {"mode": "report"})
            if not isinstance(enforcement, dict):
                raise SchemaError(
                    f"{manifest}: enforcement must be an object")
            unknown_enforcement = sorted(set(enforcement) - {"mode"})
            if unknown_enforcement:
                raise SchemaError(
                    f"{manifest}: enforcement has unknown field(s): "
                    f"{', '.join(unknown_enforcement)}")
            enforcement_mode = enforcement.get("mode", "report")
            if enforcement_mode not in ENFORCEMENT_MODES:
                raise SchemaError(
                    f"{manifest}: enforcement.mode must be 'report', "
                    "'quarantine', or 'strict'")
            explicit_edges_enabled = False
            if manifest_version == WORKSPACE_SCHEMA_VERSION_V3:
                features = payload.get("features")
                if not isinstance(features, dict):
                    raise SchemaError(
                        f"{manifest}: memdsl.workspace.v3 requires object-valued features")
                unknown_features = sorted(set(features) - {"explicit_edges"})
                if unknown_features:
                    raise SchemaError(
                        f"{manifest}: features has unknown field(s): "
                        f"{', '.join(unknown_features)}")
                if features.get("explicit_edges") != EXPLICIT_EDGES_FEATURE:
                    raise SchemaError(
                        f"{manifest}: features.explicit_edges must be "
                        f"{EXPLICIT_EDGES_FEATURE!r}")
                explicit_edges_enabled = True
        contract = (
            manifest_version,
            linking_visibility,
            enforcement_mode,
            explicit_edges_enabled,
        )
        if manifest_contract is not None and manifest_contract != contract:
            raise SchemaError(
                f"{manifest}: workspace manifests disagree on schema/linking/"
                "enforcement "
                f"contract: {manifest_contract!r} vs {contract!r}")
        manifest_contract = contract
        registry.workspace_schema_version = manifest_version
        registry.linking_visibility = linking_visibility
        registry.enforcement_mode = enforcement_mode
        registry.explicit_edges_enabled = explicit_edges_enabled
        registry.manifest_files.append(os.path.abspath(manifest))
        schemas = _strings(payload.get("schemas", []), f"{manifest}.schemas")
        base = os.path.dirname(manifest)
        for schema_path in schemas:
            registry.load_schema(os.path.join(base, str(schema_path)))
    return registry
