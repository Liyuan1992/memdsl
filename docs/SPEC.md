# Memory DSL Specification

Version: 0.1 (draft)
Status: reference specification for the `memdsl` v0.1 implementation
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

Version 0.1 deliberately does not attempt:

- Turing completeness, loops, functions, or runtime computation.
- Replacing databases, knowledge graphs, or vector stores (they are
  compilation targets and fallbacks, not the source of truth).
- Turning every conversational utterance into long-term memory.
- Automatic write pipelines (see §10; writes are reviewed).
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

### 4.1 Kinds (v0.1)

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

Reserved for future versions (parse but no typed behavior in v0.1):
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

## 7. Querying: the EvidencePack contract

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

Diagnostics are first-class product surface — they belong in a maintenance
UI, not a log file.

## 9. Grammar (v0.1)

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
- Nested blocks (`evidence { ... }`, `relations { ... }`) are single-level
  maps in v0.1.

## 10. Writing (informative, not implemented in v0.1)

Writes are not `add_memory()`. The intended pipeline:

```text
turn -> candidate extraction -> worth-remembering gate
     -> kind/force classification -> subject/scope resolution
     -> compare with existing declarations
     -> append | merge | supersede | conflict | ignore
     -> evidence + declaration write -> lint -> compile
```

The worth-remembering gate blocks low-value, ephemeral, evidence-free, or
boundary-violating content from entering long-term memory. In early
deployments **all** LLM-proposed writes go to a human review queue;
automation is earned with audited gate metrics (false positive rate, wrong
kind/force/subject rates), not assumed.

## 11. Design principles

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
for v0.1 and will be specified once the core proves useful.*
