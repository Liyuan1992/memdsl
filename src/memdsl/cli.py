"""memdsl command-line interface.

    memdsl lint PATH...              lint memory source files
    memdsl query PATH... -q TEXT     build an evidence pack for a query
    memdsl explain PATH... ID        show one declaration with relations
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

    return 2


if __name__ == "__main__":
    sys.exit(main())
