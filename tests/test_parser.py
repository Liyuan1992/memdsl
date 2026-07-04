import pytest

from memdsl.parser import ParseError, parse_text

BASIC = """
# comment
module self

use Project.Aurora

preference sleep.avoid_early_morning {
  subject: User
  claim: "Does not like waking up early."
  force: advisory
  scope: personal_routine
  confidence: medium
  tags: [sleep, routine]
  evidence {
    source: chat
    quote: "I hate early mornings."
  }
}
"""


def test_parse_basic():
    doc = parse_text(BASIC)
    assert doc.module == "self"
    assert doc.uses == ["Project.Aurora"]
    assert len(doc.declarations) == 1
    d = doc.declarations[0]
    assert d.kind == "preference"
    assert d.name == "sleep.avoid_early_morning"
    assert d.fields["claim"] == "Does not like waking up early."
    assert d.fields["tags"] == ["sleep", "routine"]
    assert d.fields["evidence"]["source"] == "chat"
    assert d.module == "self"


def test_parse_call_like_scope():
    doc = parse_text('decision x { scope: project("Aurora") status: active }')
    assert doc.declarations[0].fields["scope"] == 'project("Aurora")'


def test_parse_multiline_list():
    doc = parse_text("""
decision d {
  alternatives: [
    postgres,
    "dynamo db",
  ]
}
""")
    assert doc.declarations[0].fields["alternatives"] == ["postgres", "dynamo db"]


def test_parse_string_escapes():
    doc = parse_text('fact f { claim: "line\\nbreak \\"quoted\\"" }')
    assert doc.declarations[0].fields["claim"] == 'line\nbreak "quoted"'


def test_unterminated_block_raises():
    with pytest.raises(ParseError):
        parse_text("fact f { claim: \"x\"")


def test_unterminated_string_raises():
    with pytest.raises(ParseError):
        parse_text('fact f { claim: "never closed }')


def test_missing_colon_raises():
    with pytest.raises(ParseError):
        parse_text("fact f { claim }")
