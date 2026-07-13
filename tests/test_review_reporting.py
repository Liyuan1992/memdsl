"""Tests for replayable review digest, stats, and post-review feedback."""

import hashlib
import json

import pytest

from memdsl.review import AuditLogError, ReviewStore
from memdsl.review_reporting import (
    proposal_review_metadata,
    record_post_review,
    review_digest,
    review_stats,
)


POLICY_HASH = "1" * 64
CONTENT_HASH = "2" * 64
ASSESSMENT_HASH = "3" * 64


def _canonical_assessment_hash(assessment):
    base = {
        key: value for key, value in assessment.items()
        if key != "assessment_hash"
    }
    encoded = json.dumps(
        base,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _ts(second):
    return f"2026-07-14T00:00:{second:02d}+00:00"


def _snapshot(
    declaration_id,
    *,
    kind="demo.note",
    runtime_role="assertion",
    client="trusted-host",
    verifier="workspace_file_quote",
    relations=None,
):
    return {
        "declaration": {
            "id": declaration_id,
            "kind": kind,
            "runtime_role": runtime_role,
            "status": "candidate",
            "scope": "project:demo",
            "force": "",
            "capabilities": ["auto_approvable"],
            "has_access_policy": False,
            "relations": relations or {},
            "warnings_count": 0,
            "content_hash": CONTENT_HASH,
        },
        "context": {
            "client": client,
            "evidence": {
                "verified": True,
                "verifier": verifier,
                "source_digest": "4" * 64,
                "quote_digest": "5" * 64,
                "evidence_digest": "6" * 64,
            },
        },
        "policy": {
            "version": "memdsl.review-policy.v1",
            "policy_hash": POLICY_HASH,
            "auto_approved_today": 0,
            "max_auto_approve_per_day": 10,
        },
    }


def _propose(proposal_id, second, declaration_id=None):
    return {
        "ts": _ts(second),
        "action": "propose",
        "proposal_id": proposal_id,
        "client": "trusted-host",
        "declaration": declaration_id or f"demo.note:{proposal_id}",
    }


def _route(
    proposal_id,
    second,
    *,
    decision,
    rule="safe-notes",
    reasons=None,
    eligible=None,
    declaration_id=None,
    relations=None,
):
    snapshot = _snapshot(
        declaration_id or f"demo.note:{proposal_id}", relations=relations)
    assessment = {
        "decision": decision,
        "rule": rule,
        "reason_codes": reasons or [],
        "policy_hash": POLICY_HASH,
        "content_hash": CONTENT_HASH,
        "input_snapshot": snapshot,
        "assessment_hash": ASSESSMENT_HASH,
    }
    event = {
        "ts": _ts(second),
        "action": "route",
        "proposal_id": proposal_id,
        "decision": decision,
        "rule": rule,
        "reason_codes": reasons or [],
        "policy_hash": POLICY_HASH,
        "content_hash": CONTENT_HASH,
        "assessment_hash": ASSESSMENT_HASH,
        "input_snapshot": snapshot,
        "assessment": assessment,
    }
    if eligible is not None:
        eligible_assessment = dict(assessment)
        eligible_assessment["decision"] = eligible
        eligible_assessment["assessment_hash"] = "7" * 64
        event["eligible_route"] = eligible
        event["eligible_assessment_hash"] = "7" * 64
        event["eligible_assessment"] = eligible_assessment
    return event


def _approve(proposal_id, second, *, by="human"):
    return {
        "ts": _ts(second),
        "action": "approve",
        "proposal_id": proposal_id,
        "by": by,
        "into": "approved.mem",
        "declaration": f"demo.note:{proposal_id}",
        "forced": False,
        "assessment_hash": ASSESSMENT_HASH,
    }


def _reject(proposal_id, second):
    return {
        "ts": _ts(second),
        "action": "reject",
        "proposal_id": proposal_id,
        "by": "human",
        "reason": "not durable",
    }


def _post_review(proposal_id, second, verdict, reason="checked"):
    return {
        "ts": _ts(second),
        "action": "post_review",
        "proposal_id": proposal_id,
        "by": "human",
        "verdict": verdict,
        "reason": reason,
        "assessment_hash": ASSESSMENT_HASH,
    }


def test_proposal_metadata_uses_latest_post_review_and_reports_changes():
    entries = [
        _propose("p-auto", 0),
        _route("p-auto", 1, decision="auto_approve"),
        _approve("p-auto", 2, by="policy:safe-notes"),
        _post_review("p-auto", 3, "confirm"),
        _post_review("p-auto", 4, "flag", "source changed"),
        _post_review("p-auto", 5, "flag", "still wrong"),
        _propose("p-legacy", 6),
    ]

    metadata = proposal_review_metadata(entries)
    auto = metadata["p-auto"]
    assert auto["route"] == "auto_approved"
    assert auto["auto_approved"] is True
    assert auto["kind"] == "demo.note"
    assert auto["runtime_role"] == "assertion"
    assert auto["client"] == "trusted-host"
    assert auto["post_review_verdict"] == "flag"
    assert auto["post_review_reason"] == "still wrong"
    assert auto["post_review_events"] == 3
    assert auto["post_review_changes"] == 1

    legacy = metadata["p-legacy"]
    assert legacy["route"] == "legacy_unknown"
    assert legacy["kind"] == "legacy_unknown"
    assert legacy["runtime_role"] == "legacy_unknown"


def test_stats_replays_route_snapshots_sample_decisions_and_no_op():
    entries = [
        _propose("p-auto", 0),
        _route("p-auto", 1, decision="auto_approve"),
        _approve("p-auto", 2, by="policy:safe-notes"),
        _post_review("p-auto", 3, "confirm"),
        _propose("p-sampled-a", 4),
        _route("p-sampled-a", 5, decision="queue",
               reasons=["sampled_to_queue"]),
        _approve("p-sampled-a", 6),
        _propose("p-sampled-r", 7),
        _route("p-sampled-r", 8, decision="queue",
               reasons=["sampled_to_queue"]),
        _reject("p-sampled-r", 9),
        _propose("p-shadow", 10),
        _route("p-shadow", 11, decision="queue",
               reasons=["auto_scope_missing"], eligible="auto_approve"),
        _propose("p-pending", 12),
        _route("p-pending", 13, decision="queue", rule="manual-default"),
        _propose("p-legacy", 14),
        {
            "ts": _ts(15),
            "action": "no_op",
            "proposal_id": "p-auto",
            "attempt_id": "a-retry",
            "duplicate_of": "p-auto",
            "existing_status": "approved",
            "rule": "duplicate",
            "policy_hash": POLICY_HASH,
            "content_hash": CONTENT_HASH,
            "input_snapshot": _snapshot("demo.note:p-auto"),
        },
    ]

    stats = review_stats(entries)
    assert stats["schema_version"] == "memdsl.review.stats.v1"
    assert stats["totals"] == {
        "proposed": 6,
        "queued": 5,
        "would_auto_approve_shadow": 1,
        "sampled_to_queue": 2,
        "human_approved": 1,
        "human_rejected": 1,
        "sampled_human_approved": 1,
        "sampled_human_rejected": 1,
        "auto_approved": 1,
        "post_review_confirmed": 1,
        "post_review_flagged": 0,
        "post_review_changes": 0,
        "no_op": 1,
        "confirmation_rate": 1.0,
        "flag_rate": 0.0,
    }
    auto_group = next(
        row for row in stats["groups"]
        if row["rule"] == "safe-notes")
    assert auto_group["kind"] == "demo.note"
    assert auto_group["runtime_role"] == "assertion"
    assert auto_group["client"] == "trusted-host"
    assert auto_group["policy_hash"] == POLICY_HASH
    assert auto_group["auto_approved"] == 1
    assert auto_group["post_review_confirmed"] == 1
    legacy_group = next(
        row for row in stats["groups"]
        if row["rule"] == "legacy_unknown")
    assert legacy_group["proposed"] == 1
    assert legacy_group["queued"] == 1


def test_digest_uses_latest_digest_cursor_and_keeps_unresolved_attention():
    resolved_id = "demo.note:resolved-candidate"
    entries = [
        _propose("p-old", 0),
        _route("p-old", 1, decision="auto_approve"),
        _approve("p-old", 2, by="policy:safe-notes"),
        _propose("p-resolved", 3, resolved_id),
        _route("p-resolved", 4, decision="auto_approve",
               declaration_id=resolved_id),
        _approve("p-resolved", 5, by="policy:safe-notes"),
        _post_review("p-resolved", 6, "flag"),
        _propose("p-unresolved", 7),
        _route("p-unresolved", 8, decision="auto_approve"),
        _approve("p-unresolved", 9, by="policy:safe-notes"),
        {"ts": _ts(10), "action": "digest", "proposal_id": ""},
        _propose("p-revision", 11),
        _route(
            "p-revision", 12, decision="queue", rule="safety-floor",
            relations={"supersedes": [resolved_id],
                       "revision_of": [resolved_id]}),
        _approve("p-revision", 13),
        _post_review("p-unresolved", 14, "flag", "incorrect source"),
        _propose("p-sampled", 15),
        _route("p-sampled", 16, decision="queue",
               reasons=["sampled_to_queue"]),
    ]

    digest = review_digest(entries)
    assert digest["cursor_source"] == "last_digest"
    assert digest["since"] == _ts(10)
    assert [item["proposal_id"] for item in digest["pending"]] == ["p-sampled"]
    assert [item["proposal_id"] for item in digest["sampled_queue"]] == ["p-sampled"]
    assert {item["proposal_id"] for item in digest["auto_approvals"]} == {
        "p-old", "p-resolved", "p-unresolved"}
    assert [item["proposal_id"]
            for item in digest["unaudited_auto_approvals"]] == ["p-old"]
    assert {item["proposal_id"] for item in digest["latest_flags"]} == {
        "p-resolved", "p-unresolved"}
    assert [item["proposal_id"]
            for item in digest["revision_needed"]] == ["p-unresolved"]
    resolved = next(
        item for item in digest["latest_flags"]
        if item["proposal_id"] == "p-resolved")
    assert resolved["revision_resolved"] is True
    assert resolved["superseding_proposal_ids"] == ["p-revision"]
    assert [(item["priority"], item["proposal_id"])
            for item in digest["attention"]] == [
        (1, "p-unresolved"),
        (2, "p-old"),
        (3, "p-sampled"),
    ]
    assert digest["counts"]["events_since"] == 6
    old = next(item for item in digest["auto_approvals"]
               if item["proposal_id"] == "p-old")
    unresolved = next(item for item in digest["auto_approvals"]
                      if item["proposal_id"] == "p-unresolved")
    assert old["new_since"] is False
    assert unresolved["new_since"] is True  # its latest flag is new

    explicit = review_digest(entries, since=_ts(0))
    assert explicit["cursor_source"] == "explicit"
    assert explicit["counts"]["events_since"] == len(entries) - 1


def test_record_post_review_appends_via_store_and_only_for_policy_auto(tmp_path):
    store = ReviewStore(str(tmp_path / ".memdsl"))
    entries = [
        _propose("p-auto", 0),
        _route("p-auto", 1, decision="auto_approve"),
        _approve("p-auto", 2, by="policy:safe-notes"),
        _propose("p-queued", 3),
        _route("p-queued", 4, decision="queue"),
    ]
    route_hashes = {}
    for entry in entries:
        if entry["action"] != "route":
            continue
        assessment_hash = _canonical_assessment_hash(entry["assessment"])
        entry["assessment"]["assessment_hash"] = assessment_hash
        entry["assessment_hash"] = assessment_hash
        route_hashes[entry["proposal_id"]] = assessment_hash
    entries[2]["assessment_hash"] = route_hashes["p-auto"]
    store_path = tmp_path / ".memdsl" / "audit.log"
    store_path.parent.mkdir()
    store_path.write_text(
        "".join(json.dumps(entry) + "\n" for entry in entries),
        encoding="utf-8",
    )
    source = tmp_path / "approved.mem"
    source.write_text("unchanged\n", encoding="utf-8")

    confirmed = record_post_review(
        store, "p-auto", verdict="confirm", reason="source checked")
    assert confirmed["ok"] is True
    assert confirmed["previous_verdict"] == ""
    assert confirmed["post_review_changes"] == 0
    flagged = record_post_review(
        store, "p-auto", verdict="flag", reason="source changed")
    assert flagged["ok"] is True
    assert flagged["previous_verdict"] == "confirm"
    assert flagged["post_review_changes"] == 1
    assert "supersedes" in flagged["next_action"]
    assert source.read_text(encoding="utf-8") == "unchanged\n"

    audit = store.audit_entries(strict=True)
    latest = audit[-1]
    assert latest["action"] == "post_review"
    assert latest["verdict"] == "flag"
    assert latest["assessment_hash"] == route_hashes["p-auto"]
    assert record_post_review(
        store, "p-queued", verdict="confirm")["status"] == "not_auto_approved"
    with pytest.raises(ValueError, match="confirm.*flag"):
        record_post_review(store, "p-auto", verdict="maybe")
    with pytest.raises(ValueError, match="single line"):
        record_post_review(
            store, "p-auto", verdict="confirm", reason="line one\nline two")


def test_reporting_callers_get_strict_audit_corruption_error(tmp_path):
    store = ReviewStore(str(tmp_path / ".memdsl"))
    store_path = tmp_path / ".memdsl" / "audit.log"
    store_path.parent.mkdir()
    store_path.write_text(
        json.dumps(_propose("p-good", 0)) + "\n{broken json\n",
        encoding="utf-8",
    )

    with pytest.raises(AuditLogError, match="line 2"):
        store.audit_entries(strict=True)
