import memdsl


def test_v05_public_contract_exports():
    assert memdsl.__version__ == "0.5.0"
    assert memdsl.EVIDENCE_PACK_SCHEMA == "memdsl.evidence_pack.v1"
    assert memdsl.Workspace is not None
    assert memdsl.Declaration is not None
    assert memdsl.EvidencePack is not None
    assert memdsl.ReviewStore is not None
    assert memdsl.Proposal is not None
    assert memdsl.ValidationResult is not None
    assert callable(memdsl.staging_dir_for)
