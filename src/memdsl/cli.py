"""memdsl command-line interface.

    memdsl lint PATH...              lint memory source files
    memdsl query PATH... -q TEXT     build an evidence pack for a query
    memdsl explain PATH... ID        show one declaration with relations
    memdsl review <action> PATH...   human review queue for proposed writes
"""

from __future__ import annotations

import argparse
import sys
from typing import List

from memdsl import __version__
from memdsl.linter import has_errors, lint
from memdsl.model import Workspace
from memdsl.parser import ParseError
from memdsl.query import build_evidence_pack, explain
from memdsl.review import ReviewStore, staging_dir_for


def _load(paths: List[str]) -> Workspace:
    try:
        return Workspace.load(paths)
    except ParseError as e:
        print(f"parse error: {e}", file=sys.stderr)
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

    p_query = sub.add_parser("query", help="query memory into an evidence pack")
    p_query.add_argument("paths", nargs="+", help=".mem files or directories")
    p_query.add_argument("-q", "--query", required=True, help="query text")
    p_query.add_argument("--kind", action="append", dest="kinds",
                         help="restrict to declaration kind (repeatable)")
    p_query.add_argument("--subject", help="restrict to a subject symbol")
    p_query.add_argument("--limit", type=int, default=8)
    p_query.add_argument("--json", action="store_true", help="JSON output")

    p_explain = sub.add_parser("explain", help="show one declaration")
    p_explain.add_argument("paths", nargs="+", help=".mem files or directories")
    p_explain.add_argument("id", help="declaration id (kind:name or name)")

    p_review = sub.add_parser(
        "review", help="review queue for proposed writes (human-only)")
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

    if args.command == "review":
        return _review(args)

    return 2


def _review(args: argparse.Namespace) -> int:
    import os

    store = ReviewStore(staging_dir_for(args.paths, args.staging))

    if args.action == "list":
        proposals = store.list(status=args.status)
        if not proposals:
            print(f"no {args.status} proposals in {store.proposals_dir}")
            return 0
        for p in proposals:
            info = p.summary()
            line = f"{p.id}  [{p.status}]  {info['declaration']}"
            if p.reason:
                line += f"  -- {p.reason}"
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


if __name__ == "__main__":
    sys.exit(main())
