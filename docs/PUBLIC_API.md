# memdsl 0.5 Public Python API

memdsl 0.5 supports in-process hosts such as DigitalSelf without requiring an
MCP subprocess. Import stable entry points from the package root:

```python
from memdsl import (
    EVIDENCE_PACK_SCHEMA,
    Proposal,
    ReviewStore,
    TypeRegistry,
    ValidationResult,
    Workspace,
    build_evidence_pack,
    build_memory_map,
    lint,
    render_memory_map_text,
    staging_dir_for,
    workspace_vocabulary,
)
```

## Read path

```python
workspace = Workspace.load(["memory"])
diagnostics = lint(workspace)
pack = build_evidence_pack(workspace, "project release rules")
payload = pack.as_dict()
assert payload["schema_version"] == "memdsl.evidence_pack.v1"
```

The five layers are stable: `must`, `should`, `context`, `conflicts`, and
`missing`. Domain type names are not hard-coded into the query executor;
`runtime_role` controls layering.

Serialized packs additively expose `search_trace` (query interpretation,
applied filters, and matches a filter excluded) so a miss carries enough
information to retry instead of looking like absence.

## Navigation path

```python
from memdsl import build_memory_map, render_memory_map_text, workspace_vocabulary

map_data = build_memory_map(workspace)     # per-module index + vocabulary
text = render_memory_map_text(map_data)    # compact context-resident form
vocab = workspace_vocabulary(workspace)    # subjects/aliases/scopes/types
```

The map is a navigation projection for agents that read memory themselves:
items carry no evidence and claims are truncated, so it is never a citation
source. Hosts should load it (or `memdsl map <workspace>` / MCP
`memory_map`) at session start.

## Reviewed write path

```python
store = ReviewStore(staging_dir_for(["memory"]))
result = store.create(workspace, proposal_source, client="host-runtime")
```

`create()` only stages a proposal. Pending proposals are not loaded by
`Workspace.load()` and are not queryable. `approve()` revalidates against the
current workspace, writes atomically, appends an audit record, and is
idempotent under concurrent retries. Hosts remain responsible for permission,
identity, confirmation, and UI policy.

## Compatibility promise

Patch releases in the 0.5 line will not remove these root exports or change
the meaning of the five EvidencePack layers. New optional fields may be added
to versioned payloads. Breaking schema changes require a new schema id.
