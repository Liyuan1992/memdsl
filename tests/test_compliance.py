import json

from memdsl.cli import main as cli_main
from memdsl.compliance import check_compliance
from memdsl.linter import lint
from memdsl.model import Workspace
from memdsl.parser import parse_text


MEM_SOURCE = r'''
module checks

entity User {
  status: active
}

boundary privacy.no_family_in_public {
  subject: User
  rule: "Never include family details in public content."
  force: hard
  scope: global
  exceptions: [user_explicit_override]
  status: active
  guard {
    when_any: ["public", "blog"]
    deny_any: ["family", "daughter"]
  }
  evidence { source: chat quote: "Keep family out of public posts." }
}

boundary finance.review_purchase {
  subject: User
  rule: "Review purchases before paying."
  force: hard
  scope: purchase
  exceptions: []
  status: active
  evidence { source: chat quote: "Ask before buying." }
}
'''


def workspace():
    ws = Workspace()
    ws.add_document(parse_text(MEM_SOURCE, file="memory.mem"))
    return ws


def test_guard_blocks_denied_phrase():
    pack = check_compliance(
        workspace(), "Draft a public blog post", "My family joined the launch.")
    assert pack.verdict == "block"
    assert [v["boundary_id"] for v in pack.violations] == [
        "boundary:privacy.no_family_in_public"]
    assert pack.violations[0]["evidence"]["quote"]


def test_guard_allows_clean_candidate_and_applies_declared_exception():
    clean = check_compliance(
        workspace(), "Draft a public blog post", "The product now syncs offline.")
    assert clean.verdict == "allow"

    waived = check_compliance(
        workspace(), "Draft a public blog post", "My family joined the launch.",
        exceptions=["user_explicit_override"])
    assert waived.verdict == "allow"
    assert waived.exceptions_applied[0]["boundary_id"] == (
        "boundary:privacy.no_family_in_public")

    unrelated = check_compliance(
        workspace(), "Summarize local test results", "All tests passed.",
        exceptions=["user_explicit_override"])
    assert unrelated.verdict == "allow"
    assert unrelated.exceptions_applied == []


def test_unknown_or_undeclared_exception_fails_safe():
    review = check_compliance(
        workspace(), "Buy a subscription", "Pay for it now.",
        scope="purchase", exceptions=["made_up_override"])
    assert review.verdict == "needs_review"
    assert review.unknowns[0]["boundary_id"] == "boundary:finance.review_purchase"
    assert review.asserted_exceptions == ["made_up_override"]
    assert review.exceptions_applied == []


def test_check_never_truncates_applicable_boundaries():
    source = "\n".join(
        f'''boundary safety.rule_{index} {{
  rule: "Never emit forbidden-{index}."
  force: hard
  scope: global
  exceptions: []
  status: active
  guard {{ deny_any: ["forbidden-{index}"] }}
  evidence {{ source: test quote: "Rule {index}." }}
}}'''
        for index in range(60)
    )
    ws = Workspace()
    ws.add_document(parse_text(source, file="many.mem"))
    pack = check_compliance(ws, "prepare a response", "safe candidate")
    assert pack.verdict == "allow"
    assert len(pack.applicable_must) == 60


def test_guard_trigger_can_select_non_english_boundary():
    ws = Workspace()
    ws.add_document(parse_text('''
boundary privacy.chinese_public {
  rule: "不要在公开内容中写家人信息。"
  force: hard
  scope: publication
  exceptions: []
  status: active
  guard {
    when_any: ["公开", "博客"]
    deny_any: ["家人", "女儿"]
  }
  evidence { source: chat quote: "不要公开家人信息。" }
}
''', file="zh.mem"))
    pack = check_compliance(ws, "写一篇公开博客", "我的家人帮助了我。")
    assert pack.verdict == "block"
    assert pack.violations[0]["boundary_id"] == "boundary:privacy.chinese_public"


def test_only_active_constraints_participate_in_compliance():
    def constraint_workspace(status):
        ws = Workspace()
        ws.add_document(parse_text(f'''
boundary release.provisional_gate {{
  rule: "Never publish a secret release token."
  force: hard
  scope: global
  lifecycle {{ status: {status} }}
  guard {{ deny_any: ["secret-token"] }}
  evidence {{ source: test quote: "Keep the token private." }}
}}
''', file=f"{status}.mem"))
        return ws

    candidate = check_compliance(
        constraint_workspace("candidate"),
        "Publish a release note", "Include secret-token in the note.")
    assert candidate.verdict == "allow"
    assert candidate.applicable_must == []
    assert candidate.violations == []

    active = check_compliance(
        constraint_workspace("active"),
        "Publish a release note", "Include secret-token in the note.")
    assert active.verdict == "block"
    assert [d.id for d in active.applicable_must] == [
        "boundary:release.provisional_gate"]
    payload = active.as_dict()
    assert payload["applicable_must"][0]["status"] == "active"
    assert payload["applicable_must"][0]["lifecycle"] == {"status": "active"}
    assert payload["applicable_must"][0]["runtime_role"] == "constraint"
    text = active.render_text()
    assert "status=active" in text
    assert "runtime_role=constraint" in text
    assert 'lifecycle={"status":"active"}' in text


def test_linter_rejects_invalid_guard_regex():
    ws = Workspace()
    ws.add_document(parse_text(r'''
boundary broken.regex {
  rule: "Block a bad pattern."
  force: hard
  scope: global
  exceptions: []
  status: active
  guard { deny_regex: ["("] }
  evidence { source: test quote: "Block it." }
}
''', file="bad.mem"))
    codes = {d.code for d in lint(ws)}
    assert "invalid_guard_regex" in codes


def test_cli_check_exit_codes_and_json(tmp_path, capsys):
    source = tmp_path / "memory.mem"
    source.write_text(MEM_SOURCE, encoding="utf-8")
    code = cli_main([
        "check", str(source), "--task", "public blog",
        "--candidate", "My family joined.", "--json",
    ])
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "block"

    code = cli_main([
        "check", str(source), "--task", "buy subscription",
        "--candidate", "Pay now", "--scope", "purchase",
    ])
    assert code == 2
    assert "NEEDS_REVIEW" in capsys.readouterr().out

    code = cli_main([
        "check", str(source), "--task", "public blog", "--candidate", "",
    ])
    assert code == 2
    assert "non-empty" in capsys.readouterr().err
