"""CLI coverage for tiered review policy, digest, stats, and post-review."""

import json

from memdsl.cli import DEFAULT_REVIEW_POLICY, main as cli_main
from memdsl.mcp_service import MemdslMCPService


def _workspace(tmp_path):
    root = tmp_path / "memory"
    root.mkdir()
    (root / "memdsl.json").write_text(json.dumps({
        "schema_version": "memdsl.workspace.v1",
        "schemas": ["demo.memschema.json"],
    }), encoding="utf-8")
    (root / "demo.memschema.json").write_text(json.dumps({
        "name": "demo",
        "version": "1",
        "types": {
            "observation": {
                "runtime_role": "assertion",
                "required_fields": ["claim", "scope", "evidence"],
                "capabilities": [
                    "requires_evidence", "searchable", "auto_approvable"],
                "allow_extra_fields": False,
            },
        },
    }), encoding="utf-8")
    (root / "base.mem").write_text("module demo\n", encoding="utf-8")
    (root / "evidence.txt").write_text(
        "The synthetic deployment is healthy.\n", encoding="utf-8")
    source = (
        "demo.observation deployment.health {\n"
        "  claim: \"The synthetic deployment is healthy.\"\n"
        "  scope: \"project:synthetic\"\n"
        "  lifecycle { status: candidate }\n"
        "  evidence {\n"
        "    source: evidence.txt\n"
        "    quote: \"The synthetic deployment is healthy.\"\n"
        "  }\n"
        "}\n"
    )
    return root, source


def _enable_policy(root):
    staging = root / ".memdsl"
    staging.mkdir(exist_ok=True)
    policy = {
        "version": "memdsl.policy.v1",
        "default_route": "queue",
        "auto_merge_into": "generated/observations.mem",
        "sample_to_queue_percent": 0,
        "max_auto_approve_per_day": 5,
        "trusted_clients": ["mcp:synthetic"],
        "rules": [{
            "name": "synthetic-observations",
            "route": "auto_approve",
            "match": {
                "kind": ["demo.observation"],
                "client": ["mcp:synthetic"],
                "evidence_verifier": ["workspace_file_quote"],
            },
        }],
    }
    (staging / "policy.json").write_text(
        json.dumps(policy, indent=2), encoding="utf-8")


def test_policy_init_show_validate_is_safe_and_plain_json(tmp_path, capsys):
    root, _source = _workspace(tmp_path)
    path = str(root)

    assert cli_main(["review", "policy", "init", path]) == 0
    output = capsys.readouterr().out
    assert "automatic approval remains disabled" in output
    policy_path = root / ".memdsl" / "policy.json"
    assert json.loads(policy_path.read_text(encoding="utf-8")) == (
        DEFAULT_REVIEW_POLICY)
    assert "//" not in policy_path.read_text(encoding="utf-8")

    assert cli_main(["review", "policy", "show", path, "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["source_hash"]
    assert set(shown["automation_disabled_reasons"]) == {
        "max_auto_approve_per_day_is_zero",
        "trusted_clients_empty",
        "rules_empty",
    }
    assert cli_main(["review", "policy", "validate", path]) == 0
    assert "policy valid" in capsys.readouterr().out

    assert cli_main(["review", "policy", "init", path]) == 1
    assert "already exists" in capsys.readouterr().err
    assert cli_main(["review", "policy", "init", path, "--force"]) == 0
    assert list((root / ".memdsl").glob(".policy-*.tmp")) == []


def test_digest_stats_and_post_review_are_append_only(tmp_path, capsys):
    root, source = _workspace(tmp_path)
    _enable_policy(root)
    service = MemdslMCPService(
        [str(root)],
        scopes="read:summary,read:search,write:candidate,write:auto",
        client_name="mcp:synthetic",
    )
    submitted = service.propose(source)
    assert submitted["route"] == "auto_approved"
    proposal_id = submitted["proposal_id"]
    target = root / "generated" / "observations.mem"
    before = target.read_text(encoding="utf-8")

    assert cli_main(["review", "digest", str(root), "--json"]) == 0
    digest = json.loads(capsys.readouterr().out)
    assert digest["counts"]["unaudited_auto_approvals"] == 1
    assert digest["unaudited_auto_approvals"][0]["proposal_id"] == proposal_id

    assert cli_main(["review", "stats", str(root), "--json"]) == 0
    stats = json.loads(capsys.readouterr().out)
    assert stats["totals"]["auto_approved"] == 1
    assert stats["totals"]["post_review_confirmed"] == 0

    assert cli_main([
        "review", "audit", str(root), proposal_id,
        "--verdict", "confirm", "--reason", "source checked",
    ]) == 0
    assert "recorded confirm" in capsys.readouterr().out
    assert target.read_text(encoding="utf-8") == before

    assert cli_main(["review", "stats", str(root), "--json"]) == 0
    stats = json.loads(capsys.readouterr().out)
    assert stats["totals"]["post_review_confirmed"] == 1

    assert cli_main([
        "review", "audit", str(root), proposal_id,
        "--verdict", "flag", "--reason", "later contradicted",
    ]) == 0
    output = capsys.readouterr().out
    assert "supersedes" in output
    assert target.read_text(encoding="utf-8") == before


def test_policy_validate_rejects_invalid_config(tmp_path, capsys):
    root, _source = _workspace(tmp_path)
    staging = root / ".memdsl"
    staging.mkdir()
    (staging / "policy.json").write_text(
        '{"version":"memdsl.policy.v1","unknown":true}', encoding="utf-8")
    assert cli_main(["review", "policy", "validate", str(root)]) == 1
    assert "policy invalid" in capsys.readouterr().err
