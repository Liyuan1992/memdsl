import memdsl


def test_v06_public_contract_exports():
    assert memdsl.__version__ == "0.6.0"
    assert memdsl.EVIDENCE_PACK_SCHEMA == "memdsl.evidence_pack.v1"
    assert memdsl.Workspace is not None
    assert memdsl.Declaration is not None
    assert memdsl.EvidencePack is not None
    assert memdsl.ReviewStore is not None
    assert memdsl.Proposal is not None
    assert memdsl.ValidationResult is not None
    assert callable(memdsl.staging_dir_for)
    # 0.5.x additive navigation surfaces
    assert callable(memdsl.build_memory_map)
    assert callable(memdsl.render_memory_map_text)
    assert callable(memdsl.workspace_vocabulary)
    # Phase 2 bounded navigation is public without exporting CompiledWorkspace.
    assert memdsl.CATALOG_SCHEMA == "memdsl.catalog.v1"
    assert callable(memdsl.build_memory_catalog)
    assert memdsl.CatalogCursorError is not None
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
