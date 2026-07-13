"""Replayable review reporting built only from the append-only audit log.

The functions in this module deliberately do not accept a ``Workspace`` or a
type registry.  Historical routing reports must keep their original meaning
after schemas evolve, so all classification comes from the immutable
``route.assessment.input_snapshot`` written at proposal time.

Callers are expected to obtain entries with
``ReviewStore.audit_entries(strict=True)``.  The replay functions are pure and
return plain JSON-compatible dictionaries suitable for the CLI and MCP
surfaces.  :func:`record_post_review` is the one mutating helper; it appends a
``post_review`` event through :meth:`ReviewStore.record_audit` and never edits
proposal or memory source files.
"""

from __future__ import annotations

import copy
import datetime as _dt
from collections import defaultdict
from typing import Dict, List, Mapping, Optional, Sequence, Tuple, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - imported only for static checking
    from memdsl.review import ReviewStore


LEGACY_UNKNOWN = "legacy_unknown"
POST_REVIEW_VERDICTS = frozenset({"confirm", "flag"})

_GROUP_FIELDS = (
    "kind",
    "runtime_role",
    "rule",
    "client",
    "policy_hash",
    "evidence_verifier",
)

_COUNT_FIELDS = (
    "proposed",
    "queued",
    "would_auto_approve_shadow",
    "sampled_to_queue",
    "human_approved",
    "human_rejected",
    "sampled_human_approved",
    "sampled_human_rejected",
    "auto_approved",
    "post_review_confirmed",
    "post_review_flagged",
    "post_review_changes",
    "no_op",
)


def proposal_review_metadata(
    entries: Sequence[Mapping[str, object]],
) -> Dict[str, dict]:
    """Return latest routing and post-review metadata keyed by proposal id.

    Multiple ``post_review`` events remain in the ledger, but only the latest
    verdict is exposed as the effective verdict.  ``post_review_changes`` is
    the number of verdict transitions (repeating the same verdict is not a
    change).
    """

    replay = _replay(entries)
    metadata = _metadata_from_replay(replay)
    return {
        proposal_id: _public_metadata(item)
        for proposal_id, item in sorted(metadata.items())
    }


def review_stats(entries: Sequence[Mapping[str, object]]) -> dict:
    """Replay review statistics from route/no-op snapshots and decisions.

    Grouping never consults the current registry.  Proposals predating route
    snapshots are placed in one ``legacy_unknown`` group rather than guessed
    from their current declaration type.
    """

    replay = _replay(entries)
    metadata = _metadata_from_replay(replay)
    groups: Dict[Tuple[str, ...], dict] = {}

    def group_for(values: Mapping[str, object]) -> dict:
        key = tuple(_text(values.get(field)) or LEGACY_UNKNOWN
                    for field in _GROUP_FIELDS)
        if key not in groups:
            group = {field: value for field, value in zip(_GROUP_FIELDS, key)}
            group.update({field: 0 for field in _COUNT_FIELDS})
            groups[key] = group
        return groups[key]

    for proposal_id, item in metadata.items():
        group = group_for(item)
        record = replay["proposals"][proposal_id]
        if record.get("propose") is not None:
            group["proposed"] += 1

        route = item["route"]
        if route == "queued" or (
                route == LEGACY_UNKNOWN and item["status"] == "pending"):
            group["queued"] += 1
        if (item["decision"] == "queue"
                and item["eligible_route"] == "auto_approve"
                and route == "queued"):
            group["would_auto_approve_shadow"] += 1
        if item["sampled_to_queue"]:
            group["sampled_to_queue"] += 1
        if item["auto_approved"]:
            group["auto_approved"] += 1

        decision = _entry(record.get("decision"))
        decision_action = _text(decision.get("action"))
        decision_by = _text(decision.get("by"))
        if decision_action == "approve" and not decision_by.startswith("policy:"):
            group["human_approved"] += 1
            if item["sampled_to_queue"]:
                group["sampled_human_approved"] += 1
        elif decision_action == "reject":
            group["human_rejected"] += 1
            if item["sampled_to_queue"]:
                group["sampled_human_rejected"] += 1

        if item["post_review_verdict"] == "confirm":
            group["post_review_confirmed"] += 1
        elif item["post_review_verdict"] == "flag":
            group["post_review_flagged"] += 1
        group["post_review_changes"] += item["post_review_changes"]

    # A no-op is an attempted submission rather than a proposal.  Its own
    # immutable input_snapshot provides the grouping dimensions.
    for wrapped in replay["no_ops"]:
        event = wrapped["entry"]
        group = group_for(_group_values(event, legacy=False))
        group["no_op"] += 1

    group_rows = []
    for key in sorted(groups):
        row = groups[key]
        _add_rates(row)
        group_rows.append(row)

    totals = {field: sum(row[field] for row in group_rows)
              for field in _COUNT_FIELDS}
    _add_rates(totals)
    post_review_history = [
        {
            "proposal_id": proposal_id,
            "events": item["post_review_events"],
            "changes": item["post_review_changes"],
            "latest_verdict": item["post_review_verdict"],
        }
        for proposal_id, item in sorted(metadata.items())
        if item["post_review_events"]
    ]
    return {
        "schema_version": "memdsl.review.stats.v1",
        "totals": totals,
        "groups": group_rows,
        "post_review_history": post_review_history,
    }


def review_digest(
    entries: Sequence[Mapping[str, object]],
    *,
    since: Optional[str] = None,
) -> dict:
    """Build an operational digest from strict audit entries.

    An explicit ``since`` is inclusive.  Without one, the most recently
    appended ``digest`` event is the cursor; append order is then used so that
    events written in the same second as the cursor are not lost.  Operational
    backlog and unresolved attention are always listed, while ``new_since``
    and ``activity`` identify what changed after the cursor.
    """

    replay = _replay(entries)
    metadata = _metadata_from_replay(replay)
    cursor = _digest_cursor(replay["entries"], since)

    approved_superseders: Dict[str, List[str]] = defaultdict(list)
    for proposal_id, item in metadata.items():
        if item["status"] != "approved":
            continue
        for target in item["supersedes"]:
            approved_superseders[target].append(proposal_id)

    pending: List[dict] = []
    sampled_queue: List[dict] = []
    auto_approvals: List[dict] = []
    unaudited: List[dict] = []
    latest_flags: List[dict] = []
    revision_needed: List[dict] = []

    for proposal_id, item in sorted(metadata.items()):
        base = _digest_item(item, cursor)
        if item["status"] == "pending":
            pending.append(base)
            if item["sampled_to_queue"]:
                sampled_queue.append(copy.deepcopy(base))
        if item["auto_approved"]:
            auto_approvals.append(base)
            if not item["post_review_events"]:
                unaudited_item = copy.deepcopy(base)
                unaudited_item["next_action"] = "post-review confirm or flag"
                unaudited.append(unaudited_item)
        if item["post_review_verdict"] == "flag":
            superseders = sorted(approved_superseders.get(
                item["declaration_id"], []))
            flag_item = copy.deepcopy(base)
            flag_item.update({
                "flag_reason": item["post_review_reason"],
                "flagged_at": item["post_review_ts"],
                "superseding_proposal_ids": superseders,
                "revision_resolved": bool(superseders),
            })
            latest_flags.append(flag_item)
            if not superseders:
                needed = copy.deepcopy(flag_item)
                needed["next_action"] = (
                    "create a schema-valid declaration proposal whose "
                    "supersedes relation targets the flagged declaration, "
                    "then approve it manually"
                )
                revision_needed.append(needed)

    _sort_digest_items(pending)
    _sort_digest_items(sampled_queue)
    _sort_digest_items(auto_approvals)
    _sort_digest_items(unaudited)
    _sort_digest_items(latest_flags)
    _sort_digest_items(revision_needed)

    attention: List[dict] = []
    seen = set()
    for priority, attention_type, items in (
        (1, "revision_needed", revision_needed),
        (2, "unaudited_auto_approval", unaudited),
        (3, "sampled_queue", sampled_queue),
        (4, "pending", pending),
    ):
        for item in items:
            proposal_id = item["proposal_id"]
            if proposal_id in seen:
                continue
            seen.add(proposal_id)
            attention_item = copy.deepcopy(item)
            attention_item["priority"] = priority
            attention_item["attention_type"] = attention_type
            attention.append(attention_item)

    activity = []
    for wrapped in replay["entries"]:
        event = wrapped["entry"]
        if _text(event.get("action")) == "digest":
            continue
        if _is_recent(wrapped, cursor):
            activity.append({
                "ts": _text(event.get("ts")),
                "action": _text(event.get("action")),
                "proposal_id": _text(event.get("proposal_id")),
            })

    through = ""
    if replay["entries"]:
        through = _text(replay["entries"][-1]["entry"].get("ts"))
    counts = {
        "pending": len(pending),
        "sampled_queue": len(sampled_queue),
        "auto_approvals": len(auto_approvals),
        "unaudited_auto_approvals": len(unaudited),
        "latest_flags": len(latest_flags),
        "revision_needed": len(revision_needed),
        "attention": len(attention),
        "events_since": len(activity),
    }
    return {
        "schema_version": "memdsl.review.digest.v1",
        "since": cursor["since"],
        "cursor_source": cursor["source"],
        "through": through,
        "counts": counts,
        "pending": pending,
        "sampled_queue": sampled_queue,
        "auto_approvals": auto_approvals,
        "unaudited_auto_approvals": unaudited,
        "latest_flags": latest_flags,
        "revision_needed": revision_needed,
        "attention": attention,
        "activity": activity,
    }


def record_post_review(
    store: "ReviewStore",
    proposal_id: str,
    *,
    verdict: str,
    reason: str = "",
    by: str = "human",
) -> dict:
    """Append a human ``confirm`` or ``flag`` for a policy auto-approval.

    The helper validates eligibility against strict audit replay, records the
    route assessment hash, and leaves the proposal and all ``.mem`` files
    untouched.
    """

    clean_id = _single_line(proposal_id, "proposal_id", allow_empty=False)
    clean_verdict = _single_line(verdict, "verdict", allow_empty=False)
    if clean_verdict not in POST_REVIEW_VERDICTS:
        raise ValueError("verdict must be 'confirm' or 'flag'")
    clean_reason = _single_line(reason, "reason", allow_empty=True)
    clean_by = _single_line(by, "by", allow_empty=False)
    if clean_by.startswith("policy:"):
        raise ValueError("post-review actor must be human, not a policy actor")

    before_entries = store.audit_entries(strict=True)
    before = proposal_review_metadata(before_entries).get(clean_id)
    if before is None:
        return {"ok": False, "status": "not_found", "proposal_id": clean_id}
    if not before["auto_approved"]:
        return {
            "ok": False,
            "status": "not_auto_approved",
            "proposal_id": clean_id,
        }
    assessment_hash = before["assessment_hash"]
    if not assessment_hash:
        return {
            "ok": False,
            "status": "missing_assessment_hash",
            "proposal_id": clean_id,
        }

    previous_verdict = before["post_review_verdict"]
    details = {
        "by": clean_by,
        "verdict": clean_verdict,
        "assessment_hash": assessment_hash,
    }
    if clean_reason:
        details["reason"] = clean_reason
    store.record_audit("post_review", clean_id, **details)

    after = proposal_review_metadata(
        store.audit_entries(strict=True))[clean_id]
    result = {
        "ok": True,
        "status": "post_review_recorded",
        "action": "post_review",
        "proposal_id": clean_id,
        "verdict": clean_verdict,
        "reason": clean_reason,
        "by": clean_by,
        "assessment_hash": assessment_hash,
        "previous_verdict": previous_verdict,
        "post_review_events": after["post_review_events"],
        "post_review_changes": after["post_review_changes"],
    }
    if clean_verdict == "flag":
        result["next_action"] = (
            "create a schema-valid declaration proposal whose supersedes "
            "relation targets the flagged declaration, then approve it manually"
        )
    return result


def _replay(entries: Sequence[Mapping[str, object]]) -> dict:
    wrapped_entries = []
    proposals: Dict[str, dict] = {}
    no_ops = []
    for index, raw in enumerate(entries):
        if not isinstance(raw, Mapping):
            raise TypeError(f"audit entry {index + 1} must be an object")
        event = copy.deepcopy(dict(raw))
        wrapped = {"index": index, "entry": event}
        wrapped_entries.append(wrapped)
        action = _text(event.get("action"))
        proposal_id = _text(event.get("proposal_id"))
        if action == "no_op":
            no_ops.append(wrapped)
            continue
        if not proposal_id:
            continue
        record = proposals.setdefault(proposal_id, {
            "propose": None,
            "route": None,
            "route_fallback": None,
            "decision": None,
            "post_reviews": [],
            "events": [],
        })
        record["events"].append(wrapped)
        if action == "propose":
            record["propose"] = wrapped
        elif action == "route":
            record["route"] = wrapped
        elif action == "route_fallback":
            record["route_fallback"] = wrapped
        elif action in ("approve", "reject"):
            record["decision"] = wrapped
        elif action == "post_review":
            record["post_reviews"].append(wrapped)
    return {
        "entries": wrapped_entries,
        "proposals": proposals,
        "no_ops": no_ops,
    }


def _metadata_from_replay(replay: Mapping[str, object]) -> Dict[str, dict]:
    metadata = {}
    proposals = replay["proposals"]
    assert isinstance(proposals, Mapping)
    for proposal_id, raw_record in proposals.items():
        assert isinstance(raw_record, Mapping)
        record = raw_record
        route_wrapped = record.get("route")
        route_event = _entry(route_wrapped)
        fallback_event = _entry(record.get("route_fallback"))
        decision_event = _entry(record.get("decision"))
        propose_event = _entry(record.get("propose"))

        has_route = bool(route_event)
        route_values = (_group_values(route_event, legacy=False)
                        if has_route else _legacy_group_values())
        fields = _route_fields(route_event) if has_route else {}
        decision = _text(fields.get("decision"))
        reason_codes = _string_list(fields.get("reason_codes"))
        if fallback_event:
            fallback_reasons = _string_list(fallback_event.get("reason_codes"))
            reason_codes = _unique(reason_codes + fallback_reasons)

        decision_action = _text(decision_event.get("action"))
        decision_by = _text(decision_event.get("by"))
        auto_approved = (
            decision == "auto_approve"
            and decision_action == "approve"
            and decision_by.startswith("policy:")
        )
        if decision_action == "approve":
            status = "approved"
        elif decision_action == "reject":
            status = "rejected"
        else:
            status = "pending"

        if fallback_event and status == "pending":
            route = "queued"
        elif decision == "queue":
            route = "queued"
        elif decision == "auto_approve" and auto_approved:
            route = "auto_approved"
        elif decision == "auto_approve" and status == "approved":
            route = "approved"
        elif decision == "auto_approve":
            route = "auto_approve_pending"
        else:
            route = LEGACY_UNKNOWN

        post_reviews = record.get("post_reviews") or []
        post_summary = _post_review_summary(post_reviews)
        input_snapshot = fields.get("input_snapshot")
        declaration = _nested_mapping(input_snapshot, "declaration")
        relations = declaration.get("relations")
        if not isinstance(relations, Mapping):
            relations = {}
        eligible = fields.get("eligible_assessment")
        if not isinstance(eligible, Mapping):
            eligible = {}
        eligible_route = (
            _text(eligible.get("decision"))
            or _text(route_event.get("eligible_route"))
        )
        assessment_hash = (
            _text(fields.get("assessment_hash"))
            or _text(route_event.get("assessment_hash"))
        )
        declaration_id = (
            _text(declaration.get("id"))
            or _text(propose_event.get("declaration"))
            or _text(decision_event.get("declaration"))
        )

        events = record.get("events") or []
        latest = events[-1] if events else {"index": -1, "entry": {}}
        metadata[str(proposal_id)] = {
            "proposal_id": str(proposal_id),
            "route": route,
            "decision": decision or LEGACY_UNKNOWN,
            "rule": route_values["rule"],
            "policy_hash": route_values["policy_hash"],
            "assessment_hash": assessment_hash,
            "content_hash": _text(fields.get("content_hash")),
            "kind": route_values["kind"],
            "runtime_role": route_values["runtime_role"],
            "client": route_values["client"],
            "evidence_verifier": route_values["evidence_verifier"],
            "reason_codes": reason_codes,
            "eligible_route": eligible_route,
            "sampled_to_queue": "sampled_to_queue" in reason_codes,
            "status": status,
            "auto_approved": auto_approved,
            "declaration_id": declaration_id,
            "supersedes": _string_list(relations.get("supersedes")),
            "revision_of": _string_list(relations.get("revision_of")),
            "proposed_at": _text(propose_event.get("ts")),
            "approved_at": (
                _text(decision_event.get("ts"))
                if decision_action == "approve" else ""),
            "rejected_at": (
                _text(decision_event.get("ts"))
                if decision_action == "reject" else ""),
            "decided_by": decision_by,
            **post_summary,
            "latest_activity_ts": _text(latest["entry"].get("ts")),
            "no_op_count": 0,
            "_latest_index": latest["index"],
            "_route_index": (
                route_wrapped["index"] if route_wrapped is not None else -1),
            "_approval_index": (
                record["decision"]["index"]
                if record.get("decision") is not None
                and decision_action == "approve" else -1),
            "_post_review_index": post_summary.pop("_post_review_index"),
            "_group_is_legacy": not has_route,
        }

    for wrapped in replay["no_ops"]:
        proposal_id = _text(wrapped["entry"].get("proposal_id"))
        if proposal_id in metadata:
            metadata[proposal_id]["no_op_count"] += 1
    return metadata


def _route_fields(event: Mapping[str, object]) -> dict:
    assessment = event.get("assessment")
    if not isinstance(assessment, Mapping):
        assessment = event
    eligible = event.get("eligible_assessment")
    if not isinstance(eligible, Mapping):
        eligible = {}
    return {
        "decision": _text(assessment.get("decision"))
                    or _text(event.get("decision")),
        "rule": _text(assessment.get("rule")) or _text(event.get("rule")),
        "reason_codes": (
            assessment.get("reason_codes", event.get("reason_codes", []))),
        "policy_hash": (
            _text(assessment.get("policy_hash"))
            or _text(event.get("policy_hash"))),
        "content_hash": (
            _text(assessment.get("content_hash"))
            or _text(event.get("content_hash"))),
        "assessment_hash": (
            _text(assessment.get("assessment_hash"))
            or _text(event.get("assessment_hash"))),
        "input_snapshot": assessment.get(
            "input_snapshot", event.get("input_snapshot")),
        "eligible_assessment": eligible,
    }


def _group_values(event: Mapping[str, object], *, legacy: bool) -> dict:
    if legacy:
        return _legacy_group_values()
    fields = _route_fields(event)
    snapshot = fields.get("input_snapshot")
    declaration = _nested_mapping(snapshot, "declaration")
    context = _nested_mapping(snapshot, "context")
    evidence = context.get("evidence")
    if not isinstance(evidence, Mapping):
        evidence = {}
    return {
        "kind": _text(declaration.get("kind")) or LEGACY_UNKNOWN,
        "runtime_role": (
            _text(declaration.get("runtime_role")) or LEGACY_UNKNOWN),
        "rule": _text(fields.get("rule")) or LEGACY_UNKNOWN,
        "client": _text(context.get("client")) or LEGACY_UNKNOWN,
        "policy_hash": (
            _text(fields.get("policy_hash")) or LEGACY_UNKNOWN),
        "evidence_verifier": (
            _text(evidence.get("verifier")) or LEGACY_UNKNOWN),
    }


def _legacy_group_values() -> dict:
    return {field: LEGACY_UNKNOWN for field in _GROUP_FIELDS}


def _post_review_summary(wrapped_events: Sequence[Mapping[str, object]]) -> dict:
    verdicts = []
    latest = {}
    latest_index = -1
    for wrapped in wrapped_events:
        event = _entry(wrapped)
        verdict = _text(event.get("verdict"))
        if verdict not in POST_REVIEW_VERDICTS:
            raise ValueError(
                "post_review audit verdict must be 'confirm' or 'flag'")
        verdicts.append(verdict)
        latest = event
        latest_index = int(wrapped.get("index", -1))
    changes = sum(
        1 for previous, current in zip(verdicts, verdicts[1:])
        if previous != current)
    return {
        "post_review_verdict": verdicts[-1] if verdicts else "",
        "post_review_reason": _text(latest.get("reason")),
        "post_review_by": _text(latest.get("by")),
        "post_review_ts": _text(latest.get("ts")),
        "post_review_assessment_hash": _text(latest.get("assessment_hash")),
        "post_review_events": len(verdicts),
        "post_review_changes": changes,
        "_post_review_index": latest_index,
    }


def _digest_cursor(
    wrapped_entries: Sequence[Mapping[str, object]],
    explicit_since: Optional[str],
) -> dict:
    if explicit_since is not None:
        clean = _single_line(explicit_since, "since", allow_empty=False)
        return {
            "since": clean,
            "source": "explicit",
            "datetime": _parse_timestamp(clean, "since"),
            "index": None,
        }
    for wrapped in reversed(wrapped_entries):
        event = wrapped["entry"]
        if _text(event.get("action")) == "digest":
            stamp = _text(event.get("ts"))
            return {
                "since": stamp,
                "source": "last_digest",
                "datetime": _parse_timestamp(stamp, "digest.ts"),
                "index": wrapped["index"],
            }
    return {
        "since": "",
        "source": "beginning",
        "datetime": None,
        "index": None,
    }


def _digest_item(item: Mapping[str, object], cursor: Mapping[str, object]) -> dict:
    wrapped = {
        "index": int(item.get("_latest_index", -1)),
        "entry": {"ts": _digest_relevant_ts(item)},
    }
    return {
        "proposal_id": item["proposal_id"],
        "declaration_id": item["declaration_id"],
        "status": item["status"],
        "route": item["route"],
        "rule": item["rule"],
        "kind": item["kind"],
        "runtime_role": item["runtime_role"],
        "client": item["client"],
        "policy_hash": item["policy_hash"],
        "assessment_hash": item["assessment_hash"],
        "reason_codes": copy.deepcopy(item["reason_codes"]),
        "post_review_verdict": item["post_review_verdict"],
        "post_review_changes": item["post_review_changes"],
        "new_since": _is_recent(wrapped, cursor),
    }


def _digest_relevant_ts(item: Mapping[str, object]) -> str:
    return (
        _text(item.get("post_review_ts"))
        or _text(item.get("approved_at"))
        or _text(item.get("latest_activity_ts"))
        or _text(item.get("proposed_at"))
    )


def _is_recent(
    wrapped: Mapping[str, object],
    cursor: Mapping[str, object],
) -> bool:
    source = cursor["source"]
    if source == "beginning":
        return True
    if source == "last_digest":
        return int(wrapped.get("index", -1)) > int(cursor["index"])
    event = wrapped["entry"]
    stamp = _text(event.get("ts"))
    if not stamp:
        return False
    return _parse_timestamp(stamp, "audit ts") >= cursor["datetime"]


def _sort_digest_items(items: List[dict]) -> None:
    items.sort(key=lambda item: (
        _text(item.get("flagged_at")),
        _text(item.get("proposal_id")),
    ))


def _public_metadata(item: Mapping[str, object]) -> dict:
    return copy.deepcopy({
        key: value for key, value in item.items()
        if not key.startswith("_")
    })


def _add_rates(metrics: dict) -> None:
    reviewed = (
        metrics["post_review_confirmed"]
        + metrics["post_review_flagged"])
    metrics["confirmation_rate"] = (
        metrics["post_review_confirmed"] / reviewed if reviewed else 0.0)
    metrics["flag_rate"] = (
        metrics["post_review_flagged"] / reviewed if reviewed else 0.0)


def _entry(wrapped: object) -> dict:
    if not isinstance(wrapped, Mapping):
        return {}
    event = wrapped.get("entry")
    return event if isinstance(event, dict) else {}


def _nested_mapping(value: object, key: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        return {}
    nested = value.get(key)
    return nested if isinstance(nested, Mapping) else {}


def _string_list(value: object) -> List[str]:
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, (list, tuple)):
        return []
    return [_text(item) for item in value if _text(item)]


def _unique(values: Sequence[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _single_line(value: object, name: str, *, allow_empty: bool) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    clean = value.strip()
    if not allow_empty and not clean:
        raise ValueError(f"{name} must not be empty")
    if "\n" in clean or "\r" in clean:
        raise ValueError(f"{name} must be a single line")
    return clean


def _parse_timestamp(value: str, name: str) -> _dt.datetime:
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        stamp = _dt.datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=_dt.timezone.utc)
    return stamp.astimezone(_dt.timezone.utc)


__all__ = [
    "proposal_review_metadata",
    "record_post_review",
    "review_digest",
    "review_stats",
]
