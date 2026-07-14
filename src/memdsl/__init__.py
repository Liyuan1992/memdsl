"""memdsl: agent memory as normative source code.

A lintable, queryable memory DSL for LLM agents. Memory is written as
`.mem` source files with named, schema-typed, scoped declarations backed by
evidence -- then linted like code and queried into layered evidence packs
(MUST / SHOULD / CONTEXT / PROVISIONAL / CONFLICT / MISSING) that an LLM can
follow. Executable constraint guards can also preflight proposed actions into
CompliancePacks (ALLOW / BLOCK / NEEDS_REVIEW), while host-attested review
policies may auto-approve only narrowly scoped candidate assertions.
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
from memdsl.navigation import (
    CATALOG_SCHEMA,
    CatalogCursorError,
    build_memory_catalog,
)
from memdsl.policy import (
    AUTO_APPROVABLE_CAPABILITY,
    POLICY_VERSION,
    EvidenceVerification,
    PolicyError,
    PolicyRule,
    ProposalContext,
    ReviewPolicy,
    RoutingAssessment,
    RoutingDecision,
    declaration_content_hash,
    load_policy,
    verify_workspace_file_quote,
)
from memdsl.review import (
    AuditLogError,
    Proposal,
    ReviewStore,
    ValidationResult,
    staging_dir_for,
    workspace_fingerprint,
)
from memdsl.review_reporting import (
    proposal_review_metadata,
    record_post_review,
    review_digest,
    review_stats,
)
from memdsl.schema import SchemaError, TypeDescriptor, TypeRegistry

__version__ = "0.6.0"

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
    "build_memory_catalog",
    "CATALOG_SCHEMA",
    "CatalogCursorError",
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
    "AuditLogError",
    "PolicyError",
    "EvidenceVerification",
    "ProposalContext",
    "PolicyRule",
    "ReviewPolicy",
    "RoutingAssessment",
    "RoutingDecision",
    "POLICY_VERSION",
    "AUTO_APPROVABLE_CAPABILITY",
    "load_policy",
    "verify_workspace_file_quote",
    "declaration_content_hash",
    "workspace_fingerprint",
    "proposal_review_metadata",
    "record_post_review",
    "review_digest",
    "review_stats",
    "__version__",
]
