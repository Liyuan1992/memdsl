"""memdsl command-line interface.

    memdsl lint PATH...              lint memory source files
    memdsl map PATH...               compact per-module index of a workspace
    memdsl query PATH... -q TEXT     build an evidence pack for a query
    memdsl check PATH...             preflight a draft against MUST rules
    memdsl explain PATH... ID        show one declaration with relations
    memdsl review <action> PATH...   governed review routing and queue
    memdsl eval compliance PATH...   run constraint-compliance cases
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from typing import List

from memdsl import __version__
from memdsl.benchmark import (
    load_cases,
    render_benchmark_text,
    run_compliance_benchmark,
)
from memdsl.compliance import check_compliance
from memdsl.linter import has_errors, lint
from memdsl.model import Workspace
from memdsl.parser import ParseError
from memdsl.query import (
    build_evidence_pack,
    build_memory_map,
    explain,
    render_memory_map_text,
)
from memdsl.policy import POLICY_FILENAME, PolicyError, ReviewPolicy, load_policy
from memdsl.review import AuditLogError, ReviewStore, staging_dir_for
from memdsl.review_reporting import (
    proposal_review_metadata,
    record_post_review,
    review_digest,
    review_stats,
)
from memdsl.schema import SchemaError


DEFAULT_REVIEW_POLICY = {
    "version": "memdsl.policy.v1",
    "default_route": "queue",
    "auto_merge_into": "auto-approved.mem",
    "sample_to_queue_percent": 10,
    "max_auto_approve_per_day": 0,
    "trusted_clients": [],
    "rules": [],
}


def _atomic_write_json(path: str, payload: object) -> None:
    """Durably replace one JSON file without exposing a partial policy."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=".policy-", suffix=".tmp", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _load(paths: List[str]) -> Workspace:
    try:
        return Workspace.load(paths)
    except ParseError as e:
        print(f"parse error: {e}", file=sys.stderr)
        sys.exit(2)
    except SchemaError as e:
        print(f"schema error: {e}", file=sys.stderr)
        sys.exit(2)
    except OSError as e:
        print(f"cannot read input: {e}", file=sys.stderr)
        sys.exit(2)


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="memdsl",
        description="Agent memory as normative source code.")
    parser.add_argument("--version", action="version",
                        version=f"memdsl {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_lint = sub.add_parser("lint", help="lint .mem files")
    p_lint.add_argument("paths", nargs="+", help=".mem files or directories")
    p_lint.add_argument("--strict", action="store_true",
                        help="exit non-zero on warnings too")

    p_map = sub.add_parser(
        "map", help="compact per-module index of a workspace")
    p_map.add_argument("paths", nargs="+", help=".mem files or directories")
    p_map.add_argument("--json", action="store_true", help="JSON output")

    p_query = sub.add_parser("query", help="query memory into an evidence pack")
    p_query.add_argument("paths", nargs="+", help=".mem files or directories")
    p_query.add_argument("-q", "--query", required=True, help="query text")
    p_query.add_argument("--type", "--kind", action="append", dest="kinds",
                         help="restrict to memory type (repeatable; --kind is deprecated)")
    p_query.add_argument("--subject", help="restrict to a subject symbol")
    p_query.add_argument("--limit", type=int, default=8)
    p_query.add_argument("--json", action="store_true", help="JSON output")

    p_explain = sub.add_parser("explain", help="show one declaration")
    p_explain.add_argument("paths", nargs="+", help=".mem files or directories")
    p_explain.add_argument("id", help="declaration id (type:name or name)")

    p_types = sub.add_parser(
        "types", help="list loaded standard and domain memory types")
    p_types.add_argument("paths", nargs="+", help=".mem files or directories")
    p_types.add_argument("--json", action="store_true", help="JSON output")

    p_check = sub.add_parser(
        "check", help="preflight a proposed action or draft against MUST rules")
    p_check.add_argument("paths", nargs="+", help=".mem files or directories")
    p_check.add_argument("-t", "--task", required=True,
                         help="task or action being attempted")
    candidate = p_check.add_mutually_exclusive_group(required=True)
    candidate.add_argument("-c", "--candidate",
                           help="candidate action, answer, or draft text")
    candidate.add_argument("--candidate-file",
                           help="read candidate text from a UTF-8 file")
    p_check.add_argument("--subject", help="explicit subject symbol")
    p_check.add_argument("--scope", help="explicit constraint scope")
    p_check.add_argument("--exception", action="append", default=[],
                         dest="exceptions",
                         help="assert an allowed exception (repeatable)")
    p_check.add_argument("--json", action="store_true", help="JSON output")

    p_review = sub.add_parser(
        "review", help="governed review queue and policy routing")
    rsub = p_review.add_subparsers(dest="action", required=True)

    def _review_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("paths", nargs="+", help=".mem files or directories")
        p.add_argument("--staging",
                       help="staging dir (default: <workspace>/.memdsl)")

    r_list = rsub.add_parser("list", help="list proposals")
    _review_common(r_list)
    r_list.add_argument("--status", default="pending",
                        choices=["pending", "approved", "rejected", "all"])

    r_show = rsub.add_parser("show", help="show one proposal with its source")
    _review_common(r_show)
    r_show.add_argument("id", help="proposal id")

    r_approve = rsub.add_parser(
        "approve", help="approve a proposal and merge it into a .mem file")
    _review_common(r_approve)
    r_approve.add_argument("id", help="proposal id")
    r_approve.add_argument("--into",
                           help="target .mem file (default: <workspace>/approved.mem)")
    r_approve.add_argument("--force", action="store_true",
                           help="merge even if re-validation reports errors")

    r_reject = rsub.add_parser("reject", help="reject a proposal")
    _review_common(r_reject)
    r_reject.add_argument("id", help="proposal id")
    r_reject.add_argument("--reason", default="", help="why it was rejected")

    r_policy = rsub.add_parser(
        "policy", help="initialize, inspect, and validate review policy")
    policy_sub = r_policy.add_subparsers(dest="policy_action", required=True)
    rp_init = policy_sub.add_parser(
        "init", help="write a safe disabled policy.json template")
    _review_common(rp_init)
    rp_init.add_argument(
        "--force", action="store_true", help="replace an existing policy.json")
    rp_show = policy_sub.add_parser("show", help="show the current review policy")
    _review_common(rp_show)
    rp_show.add_argument("--json", action="store_true", help="JSON output")
    rp_validate = policy_sub.add_parser(
        "validate", help="validate policy, registry kinds, and target boundary")
    _review_common(rp_validate)

    r_digest = rsub.add_parser(
        "digest", help="review pending, sampled, auto-approved, and flagged writes")
    _review_common(r_digest)
    r_digest.add_argument("--since", help="inclusive ISO-8601 audit timestamp")
    r_digest.add_argument("--json", action="store_true", help="JSON output")

    r_stats = rsub.add_parser(
        "stats", help="replay review routing and human-quality metrics")
    _review_common(r_stats)
    r_stats.add_argument("--json", action="store_true", help="JSON output")

    r_audit = rsub.add_parser(
        "audit", help="record human confirm/flag for a policy auto-approval")
    _review_common(r_audit)
    r_audit.add_argument("id", help="auto-approved proposal id")
    r_audit.add_argument(
        "--verdict", required=True, choices=["confirm", "flag"])
    r_audit.add_argument("--reason", default="", help="human review reason")

    p_eval = sub.add_parser("eval", help="run reproducible evaluation suites")
    esub = p_eval.add_subparsers(dest="eval_kind", required=True)
    e_compliance = esub.add_parser(
        "compliance", help="run constraint-compliance benchmark cases")
    e_compliance.add_argument("paths", nargs="+",
                              help=".mem files or directories")
    e_compliance.add_argument("--cases", required=True,
                              help="JSONL compliance case file")
    e_compliance.add_argument("--json", action="store_true", help="JSON output")

    args = parser.parse_args(argv)

    if args.command == "lint":
        ws = _load(args.paths)
        diags = lint(ws)
        for d in diags:
            print(d.render())
        errors = sum(1 for d in diags if d.severity == "error")
        warnings = sum(1 for d in diags if d.severity == "warning")
        print(f"\n{len(ws.declarations)} declarations, "
              f"{errors} error(s), {warnings} warning(s)")
        if has_errors(diags) or (args.strict and warnings):
            return 1
        return 0

    if args.command == "map":
        ws = _load(args.paths)
        map_data = build_memory_map(ws)
        if args.json:
            print(json.dumps(
                {"schema_version": "memdsl.map.v1", **map_data},
                indent=2, ensure_ascii=False))
        else:
            print(render_memory_map_text(map_data))
        return 0

    if args.command == "query":
        ws = _load(args.paths)
        pack = build_evidence_pack(ws, args.query, kinds=args.kinds,
                                   subject=args.subject, limit=args.limit)
        print(pack.render_json() if args.json else pack.render_text())
        return 0

    if args.command == "explain":
        ws = _load(args.paths)
        print(explain(ws, args.id))
        return 0

    if args.command == "types":
        ws = _load(args.paths)
        items = [descriptor.as_dict() for descriptor in ws.registry.descriptors()]
        if args.json:
            print(json.dumps({
                "schema_version": "memdsl.types.v1",
                "schema_files": list(ws.registry.schema_files),
                "types": items,
            }, indent=2, ensure_ascii=False))
        else:
            for item in items:
                required = ",".join(item["required_fields"]) or "-"
                capabilities = ",".join(item["capabilities"]) or "-"
                print(
                    f"{item['name']}  role={item['runtime_role']}  "
                    f"required={required}  capabilities={capabilities}")
        return 0

    if args.command == "check":
        ws = _load(args.paths)
        candidate_text = args.candidate
        if args.candidate_file:
            try:
                with open(args.candidate_file, "r", encoding="utf-8") as handle:
                    candidate_text = handle.read()
            except OSError as exc:
                print(f"cannot read candidate: {exc}", file=sys.stderr)
                return 2
        if not str(args.task or "").strip() or not str(candidate_text or "").strip():
            print("task and candidate must both be non-empty", file=sys.stderr)
            return 2
        pack = check_compliance(
            ws, args.task, candidate_text,
            subject=args.subject,
            scope=args.scope,
            exceptions=args.exceptions,
        )
        print(pack.render_json() if args.json else pack.render_text())
        return {"allow": 0, "block": 1, "needs_review": 2}[pack.verdict]

    if args.command == "review":
        return _review(args)

    if args.command == "eval" and args.eval_kind == "compliance":
        ws = _load(args.paths)
        try:
            cases = load_cases(args.cases)
        except (OSError, ValueError) as exc:
            print(f"cannot load compliance cases: {exc}", file=sys.stderr)
            return 2
        report = run_compliance_benchmark(ws, cases)
        print(json.dumps(report, indent=2, ensure_ascii=False)
              if args.json else render_benchmark_text(report))
        return 0 if report["status"] == "passed" else 1

    return 2


def _review(args: argparse.Namespace) -> int:
    store = ReviewStore(staging_dir_for(args.paths, args.staging))

    if args.action == "policy":
        policy_path = os.path.join(store.staging_dir, POLICY_FILENAME)
        if args.policy_action == "init":
            if os.path.exists(policy_path) and not args.force:
                print(
                    f"policy already exists: {policy_path} (use --force to replace)",
                    file=sys.stderr,
                )
                return 1
            # Construct first so a programming error cannot write an invalid
            # template. The file is intentionally plain JSON with no comments.
            ReviewPolicy.from_dict(DEFAULT_REVIEW_POLICY)
            _atomic_write_json(policy_path, DEFAULT_REVIEW_POLICY)
            print(f"initialized disabled review policy: {policy_path}")
            print(
                "automatic approval remains disabled. Add auto_approvable to "
                "an explicit domain type, configure trusted_clients and an "
                "exact kind rule, set a positive daily limit, then grant "
                "write:auto in the host."
            )
            return 0

        try:
            ws = _load(args.paths)
            policy = load_policy(store.staging_dir, registry=ws.registry)
            if policy is None:
                print(
                    f"no policy at {policy_path}; all proposals require human review",
                    file=sys.stderr,
                )
                return 1 if args.policy_action == "validate" else 0
            target = store.validate_policy_target(policy, args.paths)
        except (PolicyError, OSError, ValueError) as exc:
            print(f"policy invalid: {exc}", file=sys.stderr)
            return 1

        disabled_reasons = []
        if policy.max_auto_approve_per_day == 0:
            disabled_reasons.append("max_auto_approve_per_day_is_zero")
        if not policy.trusted_clients:
            disabled_reasons.append("trusted_clients_empty")
        if not policy.rules:
            disabled_reasons.append("rules_empty")
        payload = {
            **policy.as_config_dict(),
            "source_hash": policy.source_hash,
            "policy_path": policy_path,
            "resolved_auto_merge_into": target,
            "automation_disabled_reasons": disabled_reasons,
        }
        if args.policy_action == "show":
            if args.json:
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                print(_render_policy(payload))
            return 0
        print(f"policy valid: {policy_path}")
        print(f"source_hash: {policy.source_hash}")
        print(f"auto_merge_into: {target}")
        if disabled_reasons:
            print("automation disabled: " + ", ".join(disabled_reasons))
        return 0

    if args.action in ("digest", "stats", "audit"):
        try:
            entries = store.audit_entries(strict=True)
        except AuditLogError as exc:
            print(f"audit invalid: {exc}", file=sys.stderr)
            return 1

        if args.action == "digest":
            try:
                report = review_digest(entries, since=args.since)
            except (TypeError, ValueError) as exc:
                print(f"cannot build digest: {exc}", file=sys.stderr)
                return 1
            if args.json:
                print(json.dumps(report, indent=2, ensure_ascii=False))
            else:
                print(_render_review_digest(report))
            if args.since is None:
                try:
                    store.record_audit(
                        "digest",
                        cursor_source=report["cursor_source"],
                        since=report["since"],
                        through=report["through"],
                        counts=report["counts"],
                    )
                except (AuditLogError, ValueError) as exc:
                    print(f"cannot record digest cursor: {exc}", file=sys.stderr)
                    return 1
            return 0

        if args.action == "stats":
            try:
                report = review_stats(entries)
            except (TypeError, ValueError) as exc:
                print(f"cannot replay review stats: {exc}", file=sys.stderr)
                return 1
            if args.json:
                print(json.dumps(report, indent=2, ensure_ascii=False))
            else:
                print(_render_review_stats(report))
            return 0

        try:
            result = record_post_review(
                store,
                args.id,
                verdict=args.verdict,
                reason=args.reason,
            )
        except (AuditLogError, TypeError, ValueError) as exc:
            print(f"post-review failed: {exc}", file=sys.stderr)
            return 1
        if not result["ok"]:
            print(f"post-review failed: {result['status']}", file=sys.stderr)
            return 1
        print(
            f"recorded {result['verdict']} for {result['proposal_id']} "
            f"(assessment {result['assessment_hash']})"
        )
        if result.get("next_action"):
            print("next action: " + result["next_action"])
        return 0

    if args.action == "list":
        try:
            metadata = proposal_review_metadata(store.audit_entries(strict=True))
        except AuditLogError as exc:
            print(f"audit invalid: {exc}", file=sys.stderr)
            return 1
        proposals = store.list(status=args.status)
        if not proposals:
            print(f"no {args.status} proposals in {store.proposals_dir}")
            return 0
        for p in proposals:
            info = p.summary()
            line = f"{p.id}  [{p.status}]  {info['declaration']}"
            if p.reason:
                line += f"  -- {p.reason}"
            review = metadata.get(p.id, {})
            if review:
                line += f"  route={review.get('route', 'legacy_unknown')}"
                if review.get("rule"):
                    line += f" rule={review['rule']}"
                if review.get("post_review_verdict"):
                    line += f" post_review={review['post_review_verdict']}"
            print(line)
        print(f"\n{len(proposals)} proposal(s)")
        return 0

    if args.action == "show":
        p = store.get(args.id)
        if p is None:
            print(f"proposal '{args.id}' not found", file=sys.stderr)
            return 1
        for key, value in p.summary().items():
            if value:
                print(f"{key}: {value}")
        try:
            review = proposal_review_metadata(
                store.audit_entries(strict=True)).get(p.id, {})
        except AuditLogError as exc:
            print(f"audit invalid: {exc}", file=sys.stderr)
            return 1
        for key in (
                "route", "rule", "assessment_hash", "content_hash",
                "post_review_verdict", "post_review_reason"):
            if review.get(key):
                print(f"{key}: {review[key]}")
        print("\n" + p.source.rstrip())
        return 0

    if args.action == "approve":
        ws = _load(args.paths)
        into = args.into
        if not into:
            first = os.path.abspath(args.paths[0])
            base = first if os.path.isdir(first) else os.path.dirname(first)
            into = os.path.join(base, "approved.mem")
        result = store.approve(args.id, ws, into, force=args.force)
        if not result["ok"]:
            print(f"approve failed: {result['status']}", file=sys.stderr)
            for e in result.get("errors", []):
                print(f"  error[{e['code']}] {e['message']}", file=sys.stderr)
            if result.get("hint"):
                print(f"  hint: {result['hint']}", file=sys.stderr)
            return 1
        print(f"approved {result['proposal_id']}: {result['declaration_id']} "
              f"-> {result['merged_into']}")
        for w in result.get("warnings", []):
            print(f"  warning[{w['code']}] {w['message']}")
        return 0

    if args.action == "reject":
        result = store.reject(args.id, reason=args.reason)
        if not result["ok"]:
            print(f"reject failed: {result['status']}", file=sys.stderr)
            return 1
        print(f"rejected {result['proposal_id']}")
        return 0

    return 2


def _render_policy(payload: dict) -> str:
    lines = [
        f"policy: {payload['policy_path']}",
        f"version: {payload['version']}",
        f"source_hash: {payload['source_hash']}",
        f"target: {payload['resolved_auto_merge_into']}",
        f"sample_to_queue_percent: {payload['sample_to_queue_percent']}",
        f"max_auto_approve_per_day: {payload['max_auto_approve_per_day']}",
        "trusted_clients: " + (
            ", ".join(payload["trusted_clients"]) or "(none)"),
        f"rules: {len(payload['rules'])}",
    ]
    for rule in payload["rules"]:
        lines.append(
            f"- {rule['name']} -> {rule['route']} "
            f"kind={','.join(rule['match']['kind'])}")
    disabled = payload["automation_disabled_reasons"]
    lines.append(
        "automation: disabled (" + ", ".join(disabled) + ")"
        if disabled else "automation: policy-configured (host still needs write:auto)"
    )
    return "\n".join(lines)


def _render_review_digest(report: dict) -> str:
    counts = report["counts"]
    lines = [
        f"review digest since {report['since'] or '(beginning)'} "
        f"through {report['through'] or '(no events)'}",
        (
            f"pending={counts['pending']} sampled={counts['sampled_queue']} "
            f"auto={counts['auto_approvals']} "
            f"unaudited={counts['unaudited_auto_approvals']} "
            f"flags={counts['latest_flags']} "
            f"revision_needed={counts['revision_needed']}"
        ),
    ]
    if report["attention"]:
        lines.append("")
        lines.append("ATTENTION")
        for item in report["attention"]:
            lines.append(
                f"{item['priority']}. [{item['attention_type']}] "
                f"{item['proposal_id']} {item.get('declaration_id', '')}".rstrip())
            if item.get("next_action"):
                lines.append(f"   next: {item['next_action']}")
    else:
        lines.extend(["", "ATTENTION", "- (none)"])
    return "\n".join(lines)


def _render_review_stats(report: dict) -> str:
    totals = report["totals"]
    lines = [
        "review stats",
        (
            f"proposed={totals['proposed']} queued={totals['queued']} "
            f"shadow={totals['would_auto_approve_shadow']} "
            f"auto={totals['auto_approved']} no_op={totals['no_op']} "
            f"confirmed={totals['post_review_confirmed']} "
            f"flagged={totals['post_review_flagged']}"
        ),
    ]
    if report["groups"]:
        lines.append("")
        lines.append("GROUPS")
        for group in report["groups"]:
            lines.append(
                f"- {group['kind']} role={group['runtime_role']} "
                f"rule={group['rule']} client={group['client']} "
                f"proposed={group['proposed']} queued={group['queued']} "
                f"auto={group['auto_approved']} "
                f"confirm_rate={group['confirmation_rate']:.3f} "
                f"flag_rate={group['flag_rate']:.3f}"
            )
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
