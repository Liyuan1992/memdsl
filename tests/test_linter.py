import datetime

from memdsl.linter import lint
from memdsl.model import Workspace
from memdsl.parser import parse_text

TODAY = datetime.date(2026, 7, 4)


def ws_from(text: str) -> Workspace:
    ws = Workspace()
    ws.add_document(parse_text(text))
    return ws


def codes(ws):
    return [d.code for d in lint(ws, today=TODAY)]


ENTITY = """
entity User {
  kind: Person
  canonical_name: "U"
  aliases: ["me"]
  status: active
}
"""


def test_clean_workspace_has_no_diagnostics():
    ws = ws_from(ENTITY + """
preference p.x {
  subject: User
  claim: "Prefers X."
  force: advisory
  scope: global
  status: active
  evidence { source: chat quote: "x" }
}
""")
    assert codes(ws) == []


def test_unresolved_symbol():
    ws = ws_from("""
preference p.x {
  subject: User.Ghost
  claim: "..."
  status: active
  evidence { source: chat quote: "x" }
}
""")
    assert "unresolved_symbol" in codes(ws)


def test_missing_evidence():
    ws = ws_from(ENTITY + """
fact f.x { subject: User claim: "..." status: active }
""")
    assert "missing_evidence" in codes(ws)


def test_candidate_does_not_require_evidence():
    ws = ws_from(ENTITY + """
fact f.x { subject: User claim: "..." status: candidate }
""")
    assert "missing_evidence" not in codes(ws)


def test_boundary_without_exception():
    ws = ws_from(ENTITY + """
boundary b.x {
  subject: User
  rule: "Never do X."
  force: hard
  status: active
  evidence { source: chat quote: "x" }
}
""")
    assert "boundary_without_exception" in codes(ws)


def test_type_force_mismatch():
    ws = ws_from(ENTITY + """
preference p.x {
  subject: User
  claim: "..."
  force: hard
  status: active
  evidence { source: chat quote: "x" }
}
""")
    assert "type_force_mismatch" in codes(ws)


def test_stale_state():
    ws = ws_from(ENTITY + """
state s.x {
  subject: User
  claim: "..."
  as_of: 2025-01-01
  status: active
  evidence { source: chat quote: "x" }
}
""")
    assert "stale_state" in codes(ws)


def test_duplicate_declaration_id():
    ws = ws_from(ENTITY + """
fact f.x { subject: User claim: "a" status: candidate }
fact f.x { subject: User claim: "b" status: candidate }
""")
    assert "duplicate_declaration_id" in codes(ws)


def test_ambiguous_alias():
    ws = ws_from("""
entity User.JobA { kind: Employment canonical_name: "A" aliases: ["work"] status: active }
entity User.JobB { kind: Employment canonical_name: "B" aliases: ["work"] status: active }
""")
    assert "ambiguous_alias" in codes(ws)


def test_unmarked_supersede_status():
    ws = ws_from(ENTITY + """
decision d.old {
  subject: User
  decision: "Old way."
  status: active
  evidence { source: chat quote: "x" }
}
decision d.new {
  subject: User
  decision: "New way."
  status: active
  supersedes: d.old
  evidence { source: chat quote: "y" }
}
""")
    assert "unmarked_supersede_status" in codes(ws)
