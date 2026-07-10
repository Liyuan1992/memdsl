# Memory DSL Specification

Version: 0.4 (draft)
Status: reference specification for the `memdsl` v0.4 implementation
License: [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) — you may share and adapt this document with attribution.

## 1. Core thesis

Memory DSL is not a language for humans to program in, and not a database
schema. It is an **LLM-first, declarative source language for long-term
memory**: memory gets names, modules, types, references, scopes, evidence,
lifecycle, and diagnostics — so an LLM can read memory the way it reads
code, query it precisely, maintain it safely, and *obey* it when answering.

Code makes LLMs stronger not because of syntax, but because code provides
cognitive scaffolding:

- **Stable symbols** — the same thing always has the same name.
- **Module boundaries** — read only the relevant file, not the whole corpus.
- **Typed contracts** — the type tells you the fields, behavior, and constraints.
- **References** — a declaration knows what it supports, refines, supersedes, or conflicts with.
- **Scopes** — a declaration knows when it applies and when it does not.
- **Diagnostics** — duplicates, dangling references, conflicts, and staleness are reported, not silently accumulated.

Memory DSL replicates these structural capabilities. It does not replicate
the surface syntax of Python, SQL, or YAML.

The defining feature relative to other memory systems is that declarations
are **normative**: a `boundary` is not a fact to be recalled, it is a rule
to be enforced. Retrieval output separates what an agent MUST respect from
what it SHOULD consider and what is merely context.

## 2. Non-goals

Version 0.4 deliberately does not attempt:

- Turing completeness, loops, functions, or runtime computation.
- Replacing databases, knowledge graphs, or vector stores (they are
  compilation targets and fallbacks, not the source of truth).
- Turning every conversational utterance into long-term memory.
- Fully automatic write approval (see §10; agent writes remain reviewed).
- Pretending that unstructured natural-language boundaries can be checked
  deterministically. They fail safely to `needs_review` (see §7.2).
- Multi-user permission models.

## 3. File model

### 3.1 Workspace

A workspace is a directory tree of `.mem` source files. Example layout:

```text
memories/
  self/
  projects/
  work/
  relationships/
```

### 3.2 Module

A module is the unit of local reading — the equivalent of a source file or
package. Modules are organized by *what questions read together*, not by
data source:

```text
self.identity        self.preferences      self.boundaries
projects.<name>.*    work.<name>           relationships.people
```

Do **not** create modules per chat session, per day, per tag, or per
declaration. Sources belong in evidence; tags are indexes, not reading
boundaries.

A module is declared at the top of a file, with optional imports:

```mem
module projects.aurora

use User
use Project.Aurora
```

## 4. Declarations

A declaration is the smallest independently referencable, independently
falsifiable unit of memory:

```mem
preference schedule.deep_work_mornings {
  subject: User
  claim: "Prefers deep work in the morning; meetings after 2pm."
  force: strong
  scope: scheduling
  confidence: high
  status: active
  evidence {
    source: chat
    quote: "Stop booking me into morning meetings."
  }
}
```

Every declaration answers: what is this memory called, what type is it,
who is it about, what does it assert, where does it apply, what evidence
backs it, and how does it relate to other memories.

### 4.1 Kinds (v0.4)

| Kind | Purpose | Typical behavior |
| --- | --- | --- |
| `entity` | Define a stable object and its aliases | Enters the symbol table; referenced by other declarations |
| `fact` | Stable fact | Background context; conflicts require evidence comparison |
| `preference` | A liking or inclination | Advisory by default; shapes suggestions, never forbids |
| `boundary` | Hard rule / prohibition / permission edge | MUST be respected; requires `exceptions` |
| `principle` | Long-term principle or methodology | Shapes judgment; conflicts must be surfaced, not silently resolved |
| `decision` | A choice that was made | Needs `reason` / `alternatives` / `result`; superseded by newer decisions |
| `state` | Current status | Needs `as_of`; goes stale; superseded by newer states |
| `open_issue` | Unresolved question | Never treated as fact; needs `next_action` |

A type is a semantic contract, not a tag. `preference` and `boundary` may
share a topic, but they bind an agent with completely different strength.

Reserved for future versions (parse but no typed behavior in v0.4):
`goal`, `relationship`, `skill`, `lesson`, `behavior_event`,
`behavior_pattern`, `habit`, `personhood_signal`, `counter_evidence`,
`motive_hypothesis`.

### 4.2 Force

```text
advisory   default consideration, may be overridden by the task at hand
strong     needs a visible reason to deviate
hard       binding unless a declared exception fires or the user overrides
```

"I don't like early mornings" is a `preference` with `force: advisory`.
Only explicit constraint language — "never", "don't schedule", "unless I
say so" — justifies a `boundary` with `force: hard`.

### 4.3 Scope

Scope limits where a declaration applies, preventing local preferences
from leaking into global personality:

```text
global    personal_routine    scheduling
project("Aurora")    work("User.DayJob")    relationship("Person.X")
```

### 4.4 Evidence

Evidence is the source map of a declaration. Active long-term declarations
**must** carry evidence; unconfirmed ones use `status: candidate`.

```mem
evidence {
  source: chat
  quote: "No meetings before ten. I mean it."
}
```

Evidence stores provenance, not conclusions. Answers cite declaration ids;
audits follow the evidence.

### 4.5 Relations

```text
supports    refines    depends_on    part_of
supersedes  conflicts_with  derived_from  related_to
```

`supersedes` makes the old declaration non-current (it must then be marked
`status: superseded`). `conflicts_with` keeps both alive and forces the
conflict to be shown at answer time. Overuse of `related_to` is a smell.

### 4.6 Status lifecycle

```text
candidate -> active -> stale? -> superseded | retracted | archived
```

`state` declarations stale quickly and need `as_of`. `boundary` and
`principle` should rarely expire but may be superseded or retracted.

### 4.7 Executable boundary guards (v0.4)

A boundary may carry a deterministic `guard` block for preflight checks:

```mem
boundary privacy.no_family_in_public {
  subject: User
  rule: "Never include family details in public-facing content."
  force: hard
  scope: global
  exceptions: [user_explicit_override]
  status: active
  guard {
    when_any: ["public", "blog", "social media"]
    deny_any: ["family", "wife", "daughter", "son"]
  }
  evidence {
    source: chat
    quote: "Anything about my family stays out of public posts."
  }
}
```

Supported guard fields:

| Field | Meaning |
| --- | --- |
| `when_any` | Activate the guard when any phrase occurs in task or candidate |
| `deny_any` | Violate when any phrase occurs in the candidate |
| `deny_regex` | Violate when any case-insensitive regex matches the candidate |
| `require_any` | Violate unless at least one phrase occurs in the candidate |
| `require_regex` | Violate unless at least one regex matches the candidate |

String matching is case-insensitive. Regex matching is case-insensitive and
multiline. A named exception only fires when it appears both in the
declaration's `exceptions` list and in the caller's explicit exception set.
Unknown exceptions never waive a boundary.

## 5. Symbols and aliases

Every long-lived object gets one canonical symbol:

```mem
entity User.DayJob {
  kind: Employment
  canonical_name: "DayJob"
  aliases: ["work", "day job", "the office"]
  status: active
}
```

Natural-language mentions resolve through the alias table to the canonical
symbol at both write time and query time. If an alias is ambiguous
(resolves to several symbols), the system must not guess — it raises an
`ambiguous_alias` diagnostic or an `open_issue` for review.

## 6. Granularity

A declaration should be split when the parts can independently expire,
independently conflict, or carry different force or scope. It should be
merged when the parts share subject, kind, scope, and force, and would
always change together.

Too fine: fragments with no causal texture, relation spam, maintenance
explosion. Too coarse: cannot cite, cannot supersede, cannot mark partial
conflicts.

Rule of thumb: evidence stays verbatim; declarations are medium-grained;
threads/summaries navigate; vectors are a fallback.

## 7. Querying and checking

### 7.1 The EvidencePack contract

A query returns a **layered evidence pack**, not a flat hit list:

```text
MUST      hard boundaries in scope        -> the agent must respect these
SHOULD    strong preferences, principles  -> deviate only with reason
CONTEXT   facts, states, decisions        -> background, citable by id
CONFLICT  declared conflicts among selected declarations
MISSING   explicit gaps and open issues   -> say "I don't know", don't guess
```

Layering rules:

1. Hard boundaries that share scope or subject with the matched
   declarations — or are global — always surface in MUST, even if the
   query did not lexically match them.
2. Superseded, retracted, and archived declarations never surface by
   default.
3. `open_issue` declarations surface under MISSING, never as facts.
4. Every surfaced item is cited by declaration id so the final answer can
   reference and be audited against it.

The retrieval scoring behind this contract is pluggable. The reference
implementation uses lexical overlap plus alias resolution; production
systems should substitute BM25 and/or embeddings *behind the same
contract*.

### 7.2 The CompliancePack contract (v0.4)

`memdsl check` and MCP `memory_check` preflight a proposed action, answer,
or draft. They return:

```text
verdict              allow | block | needs_review
applicable_must      hard boundaries considered for this action
violations           failed guard checks, cited by boundary id
asserted_exceptions   exception names supplied by the caller
exceptions_applied   declared exceptions explicitly asserted by the caller
unknowns             applicable rules that cannot be checked deterministically
```

Compliance applicability is narrower than EvidencePack retrieval. A hard
boundary is considered when it is global, matches an explicitly supplied
subject or scope, directly overlaps the task/candidate lexically, or has a
`when_any` guard trigger present in the task/candidate. The
checker does not fan enforcement out merely because two declarations share
a subject.

Verdict rules are fail-safe:

1. Any guard violation produces `block`.
2. With no violation, any applicable boundary lacking a valid executable
   guard produces `needs_review`.
3. `allow` means all applicable deterministic checks passed or a declared
   exception was explicitly applied. It is not a claim that arbitrary
   natural language was semantically proven safe.
4. Every violation cites its boundary id, source location, rule, matched
   condition, and evidence when available.

## 8. Diagnostics (linter)

| Code | Meaning | Severity |
| --- | --- | --- |
| `unresolved_symbol` | subject or relation target is not declared | error |
| `duplicate_declaration_id` | same id declared twice | error |
| `missing_evidence` | active long-term declaration with no evidence | error |
| `ambiguous_alias` | alias resolves to multiple entities | warning |
| `duplicate_declaration` | same kind/subject/scope/claim | warning |
| `boundary_without_exception` | hard boundary with no exceptions list | warning |
| `type_force_mismatch` | preference:hard or boundary:advisory | warning |
| `stale_state` | state expired or undated | warning |
| `unmarked_supersede_status` | superseded target still marked active | warning |
| `module_too_large` | module exceeds reading budget | warning |
| `invalid_guard` | guard is not a nested block | error |
| `invalid_guard_regex` | executable guard contains an invalid regex | error |
| `unknown_guard_field` | guard field is not defined by v0.4 | warning |
| `guard_without_rule` | guard has no deny/require condition | warning |

Diagnostics are first-class product surface — they belong in a maintenance
UI, not a log file.

## 9. Grammar (v0.4)

```text
document    := (module_stmt | use_stmt | declaration)*
module_stmt := 'module' DOTTED_NAME
use_stmt    := 'use' DOTTED_NAME
declaration := KIND NAME block
block       := '{' entry* '}'
entry       := FIELD ':' value | FIELD block
value       := STRING | ATOM | list
list        := '[' (value (',' value)*)? ']'
```

- Comments: `#` to end of line.
- Strings: double-quoted, `\n` `\t` `\"` `\\` escapes.
- ATOM: bare identifiers, dotted symbols (`User.DayJob`), numbers, ISO
  dates (`2026-06-20`), and call-form scopes (`project("Aurora")`), kept
  verbatim.
- Nested blocks (`evidence { ... }`, `relations { ... }`, `guard { ... }`)
  are single-level maps in v0.4.

## 10. Gated writing and review (v0.3+)

Writes are not `add_memory()`. The intended pipeline:

```text
turn -> candidate extraction -> worth-remembering gate
     -> kind/force classification -> subject/scope resolution
     -> compare with existing declarations
     -> append | merge | supersede | conflict | ignore
     -> evidence + declaration write -> lint -> compile
```

The implemented reference path is deliberately narrower than the full
future pipeline. MCP `memory_propose` accepts exactly one declaration,
parses it, merges it with the live workspace for fail-closed linting, and
stages it under `.memdsl/proposals/`. Pending proposals are never loaded by
`Workspace` or served by `memory_query`.

A person uses `memdsl review list/show/approve/reject`. Approval revalidates
against the current workspace, atomically replaces the target `.mem` file,
records an append-only JSONL audit event, and atomically updates proposal
state. Review decisions are serialized with a cross-process file lock.
Approval markers and unique audit events make retry recovery idempotent:
an interrupted approval cannot append the declaration twice.

The worth-remembering gate blocks low-value, ephemeral, evidence-free, or
boundary-violating content from entering long-term memory. **All**
LLM-proposed writes still require human review; automation is earned with
audited gate metrics (false positive rate, wrong kind/force/subject rates),
not assumed.

## 11. Boundary-compliance evaluation (v0.4)

The JSONL compliance case format records a task, candidate, expected verdict,
expected applicable boundary ids, expected violations, and optional scope,
subject, or asserted exceptions. `memdsl eval compliance` runs the same cases
through four deterministic modes:

```text
no_memory       no memory is consulted
flat_context    lexical boundary hits are flattened into context
evidence_pack   applicable MUST items are surfaced but not executed
compliance_gate executable guards produce allow/block/needs_review
```

The report includes verdict accuracy, unsafe-allow rate, false-block rate,
MUST recall, citation accuracy, and per-case evidence. This reference suite
tests the contract and runner reproducibly; it does not claim cross-model
agent behavior without a separately declared model adapter and run record.

## 12. Design principles

- Memory DSL is source code for LLMs to read, not a program to execute.
- Modules are the LLM's local reading boundary.
- Types are behavioral contracts, not tags.
- The symbol table owns naming; aliases resolve, never proliferate.
- Evidence is a source map.
- Relations are code-level references between memories.
- The linter gives memory the same maintenance feedback code enjoys.
- Summaries navigate; they are never facts.
- Vector search is a fallback tool, not the memory model.

---

*This specification distills a longer internal design document (June 2026)
covering module directories, query planners, shadow evaluation, and
personhood-synthesis kinds. Those layers are intentionally out of scope
for v0.4 and will be specified once the core proves useful.*
