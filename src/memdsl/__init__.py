"""memdsl: agent memory as normative source code.

A lintable, queryable memory DSL for LLM agents. Memory is written as
`.mem` source files with named, schema-typed, scoped declarations backed by
evidence -- then linted like code and queried into layered evidence
packs (MUST / SHOULD / CONTEXT / CONFLICT / MISSING) that an LLM can
follow. Executable constraint guards can also preflight proposed actions into
CompliancePacks (ALLOW / BLOCK / NEEDS_REVIEW).
"""

from memdsl.parser import parse_file, parse_text, ParseError
from memdsl.model import Workspace, Declaration
from memdsl.linter import lint
from memdsl.query import (
    EVIDENCE_PACK_SCHEMA,
    EvidencePack,
    build_evidence_pack,
    build_memory_map,
    render_memory_map_text,
    workspace_vocabulary,
)
from memdsl.compliance import check_compliance, CompliancePack
from memdsl.review import Proposal, ReviewStore, ValidationResult, staging_dir_for
from memdsl.schema import SchemaError, TypeDescriptor, TypeRegistry

__version__ = "0.5.1"

__all__ = [
    "parse_file",
    "parse_text",
    "ParseError",
    "Workspace",
    "Declaration",
    "lint",
    "build_evidence_pack",
    "build_memory_map",
    "render_memory_map_text",
    "workspace_vocabulary",
    "EvidencePack",
    "EVIDENCE_PACK_SCHEMA",
    "check_compliance",
    "CompliancePack",
    "SchemaError",
    "TypeDescriptor",
    "TypeRegistry",
    "Proposal",
    "ReviewStore",
    "ValidationResult",
    "staging_dir_for",
    "__version__",
]
