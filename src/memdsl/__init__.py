"""memdsl: agent memory as normative source code.

A lintable, queryable memory DSL for LLM agents. Memory is written as
`.mem` source files with named, typed, scoped declarations backed by
evidence -- then linted like code and queried into layered evidence
packs (MUST / SHOULD / CONTEXT / CONFLICT / MISSING) that an LLM can
follow.
"""

from memdsl.parser import parse_file, parse_text, ParseError
from memdsl.model import Workspace, Declaration
from memdsl.linter import lint
from memdsl.query import build_evidence_pack, EvidencePack

__version__ = "0.2.0"

__all__ = [
    "parse_file",
    "parse_text",
    "ParseError",
    "Workspace",
    "Declaration",
    "lint",
    "build_evidence_pack",
    "EvidencePack",
    "__version__",
]
