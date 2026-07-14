"""Release-candidate metadata and workflow assertions for 0.8.0."""

from pathlib import Path
import importlib.util
import re

import memdsl


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "0.8.0"


def test_release_version_is_consistent_across_runtime_and_project_metadata() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"\s*$', pyproject, re.MULTILINE)
    assert match is not None
    assert match.group(1) == EXPECTED_VERSION
    assert memdsl.__version__ == EXPECTED_VERSION
    assert f"## {EXPECTED_VERSION} - 2026-07-14" in (
        ROOT / "CHANGELOG.md"
    ).read_text(encoding="utf-8")


def test_ci_covers_core_mcp_security_and_artifact_release_gates() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    for version in ("3.9", "3.10", "3.11", "3.12"):
        assert f'"{version}"' in workflow
    assert 'python-version: ["3.10", "3.12"]' in workflow
    assert '.[dev,mcp]' in workflow
    assert "test_phase_three_indexed_query_trace.py" in workflow
    assert "test_phase_four_use_dialect.py" in workflow
    assert "test_phase_five_quarantine_enforcement.py" in workflow
    assert "release_checks.py artifacts" in workflow
    assert "release_fresh_install.py" in workflow


def test_publish_workflow_runs_complete_gates_before_upload() -> None:
    workflow = (ROOT / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )
    publish_index = workflow.index("pypa/gh-action-pypi-publish")
    required = [
        '.[dev,mcp]',
        "release_checks.py version",
        "python -m compileall",
        "python -m pytest -q",
        "python -m twine check",
        "release_checks.py artifacts",
        "release_fresh_install.py",
    ]
    for command in required:
        assert command in workflow
        assert workflow.index(command) < publish_index


def test_artifact_member_privacy_rules_reject_runtime_and_private_inputs() -> None:
    script = ROOT / "scripts" / "release_checks.py"
    spec = importlib.util.spec_from_file_location("release_checks", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module._check_member_name("memdsl-0.8.0/examples/alex/self.mem") == []
    assert module._check_member_name(
        "memdsl-0.8.0/tests/fixtures/phase_minus_one/baseline.mem"
    ) == []
    for forbidden in (
        "memdsl-0.8.0/approved.mem",
        "memdsl-0.8.0/private/workspace.mem",
        "memdsl-0.8.0/.memdsl/audit.log",
        "memdsl-0.8.0/docs/launch_article_zh.md",
        "memdsl-0.8.0/.env.production",
        "memdsl-0.8.0/cache.sqlite3",
        "memdsl-0.8.0/id_ed25519",
    ):
        assert module._check_member_name(forbidden), forbidden
