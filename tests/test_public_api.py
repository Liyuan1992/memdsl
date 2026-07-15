import memdsl


def test_v09_experimental_public_contract_preserves_v08_exports():
    assert memdsl.__version__ == "0.9.0.dev0"
    assert memdsl.EVIDENCE_PACK_SCHEMA == "memdsl.evidence_pack.v1"
    assert memdsl.Workspace is not None
    assert memdsl.Declaration is not None
    assert memdsl.CompiledWorkspace is not None
    assert callable(memdsl.compile_workspace)
    compiled_doc = (memdsl.CompiledWorkspace.__doc__ or "").lower()
    assert "public immutable, rebuildable index handle" in compiled_doc
    assert "source declarations remain the normative authority" in compiled_doc
    assert "internal" not in compiled_doc
    assert memdsl.EvidencePack is not None
    assert memdsl.ReviewStore is not None
    assert memdsl.Proposal is not None
    assert memdsl.ValidationResult is not None
    assert callable(memdsl.staging_dir_for)
    # 0.5.x additive navigation surfaces
    assert callable(memdsl.build_memory_map)
    assert callable(memdsl.render_memory_map_text)
    assert callable(memdsl.workspace_vocabulary)
    # CompiledWorkspace is a public rebuildable handle; Source stays authority.
    assert memdsl.CATALOG_SCHEMA == "memdsl.catalog.v1"
    assert callable(memdsl.build_memory_catalog)
    assert memdsl.CatalogCursorError is not None
    # Phase 3 deterministic graph navigation is a new bounded public surface.
    assert memdsl.TRACE_SCHEMA == "memdsl.trace.v1"
    assert callable(memdsl.trace_memory)
    assert memdsl.TraceAnchorError is not None
    assert memdsl.TraceCursorError is not None
    # Phase 5 opt-in enforcement uses new schemas and a public ResolvedView.
    assert memdsl.RESOLVED_VIEW_SCHEMA == "memdsl.resolved_view.v1"
    assert memdsl.RESOLVED_EVIDENCE_PACK_SCHEMA == "memdsl.evidence_pack.v2"
    assert memdsl.CATALOG_SCHEMA_V2 == "memdsl.catalog.v2"
    assert memdsl.TRACE_SCHEMA_V2 == "memdsl.trace.v2"
    assert memdsl.QUERY_SCHEMA == "memdsl.query.v2"
    assert memdsl.LIST_SCHEMA == "memdsl.list.v2"
    assert memdsl.EXPLAIN_SCHEMA == "memdsl.explain.v2"
    assert memdsl.CHECK_SCHEMA == "memdsl.check.v2"
    assert memdsl.ViewContext is not None
    assert memdsl.ResolvedView is not None
    assert memdsl.ENFORCEMENT_TABLE["duplicate_declaration_id"].strict == (
        "workspace")
    assert callable(memdsl.resolve_view)
    assert callable(memdsl.build_resolved_evidence_pack)
    assert callable(memdsl.build_resolved_query)
    assert callable(memdsl.build_resolved_list)
    assert callable(memdsl.build_resolved_explain)
    assert callable(memdsl.build_resolved_check)
    # 0.6 governed automation and replayable review surfaces
    assert memdsl.POLICY_VERSION == "memdsl.policy.v1"
    assert memdsl.AUTO_APPROVABLE_CAPABILITY == "auto_approvable"
    assert memdsl.PolicyError is not None
    assert memdsl.AuditLogError is not None
    assert memdsl.EvidenceVerification is not None
    assert memdsl.ProposalContext is not None
    assert memdsl.PolicyRule is not None
    assert memdsl.ReviewPolicy is not None
    assert memdsl.RoutingAssessment is not None
    assert memdsl.RoutingDecision is not None
    assert callable(memdsl.load_policy)
    assert callable(memdsl.verify_workspace_file_quote)
    assert callable(memdsl.declaration_content_hash)
    assert callable(memdsl.workspace_fingerprint)
    assert callable(memdsl.proposal_review_metadata)
    assert callable(memdsl.record_post_review)
    assert callable(memdsl.review_digest)
    assert callable(memdsl.review_stats)
    # Phase 6 is an additive experimental line; 0.8 contracts above stay exact.
    assert memdsl.ExplicitEdge is not None
    assert memdsl.EdgeLifecycleEvent is not None
    assert memdsl.EdgeRelationDescriptor is not None
    assert memdsl.EDGE_CATALOG_SCHEMA == "memdsl.explicit_edges.experimental.v1"
    assert callable(memdsl.build_explicit_edge_catalog)
    assert callable(memdsl.explain_explicit_edge)
    assert callable(memdsl.build_edge_transition_source)
    assert callable(memdsl.confirm_edge_proposal)
