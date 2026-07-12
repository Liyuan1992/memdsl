# AGENTS.md - memdsl

This project is a public, reusable language and runtime for declarative,
review-gated memory.

## Open-Source Generality And Privacy Boundary

- `memdsl` must remain independent of DigitalSelf, rawmem, and any one user's
  identity, memory model, filesystem layout, or product workflow.
- Keep DigitalSelf-specific schemas, candidate generation, migration logic,
  review policy, UI integration, and runtime adapters in the DigitalSelf
  repository. A change may enter `memdsl` only when it is a generic language,
  parser, schema, review, query, MCP, or storage capability that stands on its
  own with neutral documentation and tests.
- The core package must not import DigitalSelf or rawmem. Provenance and
  integration contracts should remain implementation-neutral; consuming
  projects own their adapters.
- Never commit or publish a real memory workspace, `approved.mem`, `.memdsl`
  review store, proposals, user profile, source evidence, local configuration,
  `.env` files, credentials, logs, databases, backups, machine-specific
  absolute paths, or live IDs/hashes.
- Tests, examples, documentation, wheels, and sdists must use small,
  explicitly synthetic fixtures with fictional identities and fake
  credentials. Inspect built artifacts before publishing; `.gitignore` alone
  is not sufficient evidence that a release is safe.
- If a request would hard-code one private product's semantics into memdsl,
  prefer a schema/plugin/adapter owned by that product or pause and ask for a
  genuinely reusable contract.

## Product Boundary

- Treat source declarations as the normative memory authority; indexes and
  projections are rebuildable products.
- Keep proposal, review, and approval gates explicit. Pending declarations are
  not queryable durable memory.
- Preserve append-only review and audit behavior. Do not silently rewrite
  approved history.
- Keep domain types extensible through public schemas rather than fixed private
  product enums.

## Engineering Defaults

- Prefer small public contracts with deterministic parsing, linting, review,
  and query behavior.
- Avoid dependencies on a specific host application, database, vector store,
  or model provider.
- Keep examples under `examples/` fictional and safe to publish.
- Put temporary review stores only in disposable test workspaces, never in
  shipped example workspaces.

## Verification

- Follow `.agents/skills/verify/SKILL.md` for the complete CLI, MCP, and gated
  write-path verification workflow.
- Run the test suite after changes and exercise proposed public behavior in a
  temporary workspace.
- Inspect wheel and sdist contents before release for private paths, secrets,
  runtime workspaces, and unintended generated files.
