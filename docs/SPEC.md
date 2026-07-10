# Memory DSL Specification

Version: 0.5 (draft)
Status: reference specification for the `memdsl` v0.5 implementation
License: [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/)

## 1. Core thesis

Memory DSL is an LLM-first, declarative source language for governed
long-term memory. Memory gets stable ids, evidence, scope, confidence,
lifecycle, access policy, relations, diagnostics, and behavioral roles so an
agent can read memory the way it reads code.

Version 0.5 separates two layers that earlier versions mixed together:

```text
core memory record     claim / evidence / scope / confidence / lifecycle /
                       access policy / relations

domain type system     coding.project_rule / assistant.commitment /
                       writing.voice_preference / any workspace-defined type
```

The core does not own a universal taxonomy of human memory. A coding agent,
personal assistant, writing system, and research tool may define different
types without changing memdsl Python code.

Domain types compile to a small stable set of **runtime roles**. Runtime roles
tell query and compliance how to behave; domain types tell users what a
memory means in their own field.

## 2. Non-goals

Version 0.5 deliberately does not attempt:

- Turing completeness, loops, functions, or arbitrary runtime computation.
- Replacing databases, vector stores, or knowledge graphs.
- Defining one correct ontology for all people and domains.
- Fully automatic write approval; agent writes remain human-reviewed.
- Identity-provider integration or complete multi-tenant authorization.
  Access policy is represented, validated, and transported, while external
  runtimes remain responsible for binding identities to it.
- Pretending arbitrary natural-language constraints can be checked
  deterministically. Unexecutable constraints produce `needs_review`.

## 3. Workspace and schema model

### 3.1 Workspace

A workspace is one or more `.mem` files or directories. A directory may
contain `memdsl.json`:

```json
{
  "schema_version": "memdsl.workspace.v1",
  "schemas": [
    "coding.memschema.json",
    "company-policy.memschema.json"
  ]
}
```

Schema paths are relative to the manifest. The built-in
`memdsl.standard@1` type pack is always loaded for backward compatibility.
Workspace schemas add namespaced domain types to the same `TypeRegistry`.
`schema_version` is required and must currently be `memdsl.workspace.v1`;
unsupported manifest versions fail closed.

Schema parse errors, missing files, incompatible duplicate type names, and
invalid runtime roles fail closed before memory files are served.

### 3.2 Modules

A module is a local reading boundary declared in `.mem` source:

```mem
module projects.aurora
use Project.Aurora
```

Modules group declarations that answer related questions. Sources belong in
evidence; they should not become one module per chat session or day.

### 3.3 Schema files

A `.memschema.json` file defines domain types:

```json
{
  "name": "coding",
  "version": "1",
  "types": {
    "project_rule": {
      "runtime_role": "constraint",
      "required_fields": ["claim", "evidence", "scope"],
      "optional_fields": ["rationale", "owner"],
      "search_fields": ["rationale", "owner"],
      "capabilities": [
        "requires_evidence",
        "searchable",
        "enforceable",
        "guardable"
      ],
      "defaults": {"force": "hard", "status": "active"},
      "allowed_forces": ["hard"],
      "allow_extra_fields": false
    }
  }
}
```

The registered type name is `coding.project_rule`. Namespaces prevent two
domain packs from accidentally redefining each other's vocabulary.

Schemas may also be registered programmatically with `TypeRegistry` and
`TypeDescriptor`.

## 4. Universal memory record

A declaration is the smallest independently citable and reviewable memory:

```mem
coding.project_rule git.no_force_push {
  subject: Repository.Memdsl
  claim: "Never force-push the main branch."
  scope: repository("memdsl")
  confidence: high
  lifecycle { status: active }
  access_policy {
    readers: [owner, coding_agent]
    writers: [maintainer]
    reviewers: [maintainer]
    export: internal
  }
  evidence {
    source: AGENTS.md
    quote: "Do not force-push."
  }
}
```

Universal fields:

| Field | Meaning |
| --- | --- |
| `subject` | Stable symbol this memory is about |
| `claim` | Primary human-readable assertion or rule |
| `evidence` | Provenance and verbatim source material |
| `scope` | Where the memory applies |
| `confidence` | Confidence supplied by the author or extraction process |
| `lifecycle` | Status and temporal validity |
| `access_policy` | Readers, writers, reviewers, and export posture |
| `relations` | Typed links to other memories |
| `force` | Optional binding strength used by type schemas |
| `guard` / `exceptions` | Optional deterministic compliance data |

Type schemas may add domain fields such as `symptoms`, `fix`, `cadence`,
`counterparty`, `traits`, or `example`.

### 4.1 Evidence

Evidence is a source map, not a conclusion:

```mem
evidence {
  source: issue_tracker
  quote: "The duplicate write occurred under concurrent approval."
}
```

Types with the `requires_evidence` capability fail lint when an active
declaration lacks evidence. Candidate memories may remain unconfirmed.

### 4.2 Scope

Scope prevents local rules from leaking globally:

```text
global
calendar
repository("memdsl")
component("review")
relationship("Person.Editor")
publication("team_blog")
```

Scopes are domain values. The core stores and compares them without owning
their ontology.

### 4.3 Confidence

Confidence is part of the universal record. The reference lexical retriever
uses `high` as a small tie-break boost; domain runtimes may interpret richer
confidence policies behind the same record contract.

### 4.4 Lifecycle

Preferred v0.5 form:

```mem
lifecycle {
  status: active
  as_of: 2026-07-10
  valid_until: 2026-12-31
}
```

Lifecycle statuses include `candidate`, `active`, `superseded`, `retracted`,
and `archived`. For backward compatibility, top-level `status`, `as_of`, and
`valid_until` still compile into the same lifecycle record.

Types with the `temporal` capability receive staleness diagnostics.

### 4.5 Access policy

```mem
access_policy {
  readers: [owner, coding_agent]
  writers: [owner]
  reviewers: [owner, maintainer]
  export: denied
}
```

v0.5 validates and exposes access policy through Python, JSON, CLI, and MCP.
The reference runtime does not claim to authenticate these identities; an
embedding application must bind its principals to the policy.

### 4.6 Relations

Built-in relation names:

```text
supports  refines  depends_on  part_of  supersedes
conflicts_with  derived_from  related_to  revision_of
```

`supersedes` removes the target from default query results.
`conflicts_with` keeps both declarations visible under CONFLICT.

## 5. Extensible type system

### 5.1 Runtime roles

Every memory type maps to one of five stable roles:

| Runtime role | EvidencePack behavior |
| --- | --- |
| `symbol` | Enters symbol/alias resolution; excluded from ordinary hits |
| `constraint` | Surfaces under MUST when applicable |
| `guidance` | Surfaces under SHOULD |
| `assertion` | Surfaces under CONTEXT |
| `question` | Surfaces under MISSING, never as fact |

Runtime roles are execution protocol, not a domain ontology. For example,
`coding.project_rule`, `assistant.commitment`, and `writing.taboo_topic` may
all compile to `constraint` while retaining different fields and validators.

### 5.2 Type descriptor

A `TypeDescriptor` defines:

```text
name
runtime_role
required_fields / optional_fields
claim_fields / search_fields
capabilities
defaults
allowed_forces
role_field / role_map
allow_extra_fields
schema name and version
```

`role_field` and `role_map` support types whose runtime behavior depends on a
field. The standard `preference` type, for example, maps `force: strong` to
`guidance` while advisory preferences remain assertions.

Fields referenced by `claim_fields`, `search_fields`, `defaults`, or
`role_field` are part of the descriptor's allowed field contract even when
they are not repeated in `optional_fields`.

### 5.3 Capabilities

Capabilities recognized by the reference runtime include:

| Capability | Effect |
| --- | --- |
| `symbol` | Defines canonical symbols and aliases |
| `searchable` | Eligible for query scoring |
| `requires_evidence` | Active declarations need evidence |
| `temporal` | Lifecycle receives staleness checks |
| `enforceable` | Constraint may enter deterministic compliance |
| `guardable` | Type may declare a `guard` block |
| `exceptions_recommended` | Linter asks for explicit exceptions |

Unknown capabilities may be carried for external runtimes. Core behavior is
only attached to capabilities the runtime understands.

### 5.4 Standard compatibility pack

Pre-v0.5 workspaces continue to load unchanged through
`memdsl.standard@1`:

| Standard type | Runtime role |
| --- | --- |
| `entity` | symbol |
| `fact`, `decision`, `state`, `goal` | assertion |
| `preference` | assertion or guidance according to force |
| `principle` | guidance |
| `boundary` | constraint |
| `open_issue` | question |

Other previously reserved standard names also remain generic assertions.
There is no implicit `User` symbol in v0.5; a workspace must declare every
subject it references.

## 6. DSL grammar

```text
document    := (module_stmt | use_stmt | declaration)*
module_stmt := 'module' DOTTED_NAME
use_stmt    := 'use' DOTTED_NAME
declaration := TYPE MEMORY_NAME block
block       := '{' entry* '}'
entry       := FIELD ':' value | FIELD block
value       := STRING | ATOM | list
list        := '[' (value (',' value)*)? ']'
```

`TYPE` may be a standard name (`boundary`) or a namespaced domain type
(`coding.project_rule`). Parsing accepts the syntax; linting fails closed if
no loaded schema defines the type.

Nested maps such as `evidence`, `lifecycle`, `access_policy`, `relations`,
and `guard` are single-level blocks in v0.5.

## 7. Querying: EvidencePack

A query returns a layered pack:

```text
MUST      applicable constraint memories
SHOULD    guidance memories
CONTEXT   scored assertion memories
CONFLICT  declared conflicts among selected memories
MISSING   question memories and explicit gaps
```

Layering depends on runtime role, never on a hard-coded domain type name.
Superseded, retracted, and archived memories do not surface by default.
Every item carries its id, type, runtime role, capabilities, evidence,
lifecycle, confidence, and access policy.

The stable JSON envelope is `memdsl.evidence_pack.v1`. Every serialized pack
contains `schema_version`, and scored CONTEXT entries additionally expose
`score` and `matched_terms`. Hosts may add their own runtime projection fields,
but must preserve the five layers and declaration ids.

The reference scorer remains lexical plus alias resolution. Retrieval
backends may be replaced without changing EvidencePack semantics.

## 8. CompliancePack

`memdsl check` and MCP `memory_check` preflight a candidate against
applicable `constraint` memories.

```text
verdict                  allow | block | needs_review
applicable_constraints   constraint memories considered
violations               failed guards, cited by memory id and type
asserted_exceptions      exception names supplied by the caller
exceptions_applied       declared exceptions that actually fired
unknowns                 constraints that cannot be checked deterministically
```

Deterministic execution requires both `enforceable` and `guardable`
capabilities. A constraint without those capabilities remains a MUST item but
produces `needs_review` rather than being ignored.

Supported guard fields:

| Field | Meaning |
| --- | --- |
| `when_any` | Trigger when a phrase occurs in task or candidate |
| `deny_any` | Violate when a phrase occurs in candidate |
| `deny_regex` | Violate when a regex matches candidate |
| `require_any` | Violate unless one phrase occurs in candidate |
| `require_regex` | Violate unless one regex matches candidate |

`applicable_must` and `boundary_id` remain deprecated JSON aliases for v0.4
clients. New clients should use generic memory ids and
`applicable_constraints`.

## 9. Diagnostics

Universal diagnostics include:

| Code | Meaning |
| --- | --- |
| `unknown_memory_type` | No loaded schema defines the declaration type |
| `missing_required_field` | Type schema requires a missing field |
| `unknown_type_field` | Strict type schema rejects a field |
| `missing_evidence` | Active evidence-required memory lacks evidence |
| `unresolved_symbol` | Subject or relation target is unknown |
| `duplicate_declaration_id` | Stable id is declared twice |
| `duplicate_declaration` | Type/subject/scope/claim duplicate another memory |
| `type_force_mismatch` | Force is outside the type descriptor policy |
| `stale_memory` | Temporal memory is expired, old, or undated |
| `invalid_guard_regex` | Guard regex is invalid |
| `invalid_access_policy` | Access policy is not a nested map |
| `module_too_large` | Module exceeds the reading budget |

The standard compatibility pack may preserve older diagnostic aliases such
as `boundary_without_exception` and `stale_state`.

## 10. Gated writing and review

MCP `memory_propose` accepts exactly one declaration and validates it against
the live workspace's `TypeRegistry`. A proposal using an unknown domain type
or missing a schema-required field fails before staging.

Pending proposals live under `.memdsl/proposals/` and are never served as
memory. Human approval revalidates against the current schema and workspace,
atomically updates the target `.mem` file, appends an audit event, and updates
proposal state. Locks and idempotent markers make interrupted approval safe
to retry.

The supported Python entry points are `ReviewStore`, `Proposal`,
`ValidationResult`, and `staging_dir_for`, exported from the top-level
`memdsl` package. Agents may propose; approval remains an explicit host or
human action.

## 11. Type discovery surfaces

Loaded types are discoverable through:

```text
Python       Workspace.registry / TypeRegistry
CLI          memdsl types <workspace> [--json]
MCP tool     memory_types
MCP resource memdsl://types
```

Agents should inspect loaded types before proposing memory instead of
inventing a standard taxonomy.

## 12. Compliance evaluation

JSONL compliance cases can reference any type that compiles to
`constraint`. `memdsl eval compliance` compares:

```text
no_memory
flat_context
evidence_pack
compliance_gate
```

Reports include verdict accuracy, unsafe-allow rate, false-block rate,
constraint recall, citation accuracy, and per-case results. The v0.4
`boundary_recall` metric remains as a compatibility alias.

## 13. Design principles

- The core owns memory record semantics, not a universal human ontology.
- Domain types compile to stable runtime roles and capabilities.
- Users learn their domain vocabulary, not the library author's worldview.
- Evidence is a source map.
- Scope prevents behavioral leakage.
- Lifecycle and access policy belong to every domain.
- Unknown types and incompatible schemas fail closed.
- Standard types are a compatibility pack, not the only allowed worldview.
- Types are discoverable and versioned.
- Vector search is a backend, not the memory model.
