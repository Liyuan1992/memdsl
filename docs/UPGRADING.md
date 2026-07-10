# Upgrading to memdsl 0.5

## From 0.4

Existing standard workspaces continue to load through the compatibility type
pack. No `.mem` rewrite is required.

Hosts should make these changes:

1. Pin `memdsl==0.5.0` instead of following `main`.
2. Check `EvidencePack.as_dict()["schema_version"]` for
   `memdsl.evidence_pack.v1`.
3. Use `runtime_role` and `capabilities`; do not route on a closed list of
   domain type names.
4. Import `ReviewStore` and related reviewed-write types from `memdsl`, not
   private modules.
5. Continue enforcing real identity and permissions in the host. memdsl
   represents access policy but does not provide an identity provider.

Pending proposals remain invisible until approval. Do not migrate or approve
private memory automatically during a package upgrade.
