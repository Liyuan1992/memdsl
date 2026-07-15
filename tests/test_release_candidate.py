"""0.9.0 release metadata and inherited release-gate assertions."""

from pathlib import Path
import importlib.util
import re

import memdsl


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "0.9.0"
EXPECTED_HATCHLING = "1.31.0"


def test_release_version_is_consistent_across_runtime_and_project_metadata() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"\s*$', pyproject, re.MULTILINE)
    assert match is not None
    assert match.group(1) == EXPECTED_VERSION
    assert memdsl.__version__ == EXPECTED_VERSION
    assert f"## {EXPECTED_VERSION} - 2026-07-16" in (
        ROOT / "CHANGELOG.md"
    ).read_text(encoding="utf-8")


def test_release_source_bytes_and_build_backend_are_canonical() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "* text=auto eol=lf" in attributes
    assert "*.bat text eol=crlf" in attributes
    assert "*.cmd text eol=crlf" in attributes

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    exact = f'hatchling=={EXPECTED_HATCHLING}'
    assert f'requires = ["{exact}"]' in pyproject
    assert exact in pyproject


def test_ci_covers_core_mcp_security_and_artifact_release_gates() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    assert 'MEMDSL_RELEASE_VERSION: "0.9.0"' in workflow
    assert 'SOURCE_DATE_EPOCH: "1784077269"' in workflow
    for version in ("3.9", "3.10", "3.11", "3.12"):
        assert f'"{version}"' in workflow
    assert 'python-version: ["3.10", "3.12"]' in workflow
    assert '.[dev,mcp]' in workflow
    assert "test_phase_three_indexed_query_trace.py" in workflow
    assert "test_phase_four_use_dialect.py" in workflow
    assert "test_phase_five_quarantine_enforcement.py" in workflow
    assert "test_phase_six_explicit_edges.py" in workflow
    assert "release_checks.py paper" in workflow
    assert "release_checks.py source-date-epoch" in workflow
    assert "release_checks.py source-tree" in workflow
    assert "release_checks.py build-toolchain" in workflow
    assert "python -m build --no-isolation" in workflow
    assert "cffconvert --validate" in workflow
    assert "release_checks.py artifacts" in workflow
    assert "release_fresh_install.py" in workflow


def test_publish_workflow_runs_complete_gates_before_upload() -> None:
    workflow = (ROOT / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )
    assert 'SOURCE_DATE_EPOCH: "1784077269"' in workflow
    assert "test_phase_six_explicit_edges.py" in workflow
    publish_index = workflow.index("pypa/gh-action-pypi-publish")
    required = [
        '.[dev,mcp]',
        "release_checks.py version",
        "release_checks.py source-date-epoch",
        "release_checks.py source-tree",
        "release_checks.py build-toolchain",
        "release_checks.py paper",
        "cffconvert --validate",
        "python -m compileall",
        "python -m pytest -q",
        "python -m build --no-isolation",
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

    prefix = f"memdsl-{EXPECTED_VERSION}"
    assert module._check_member_name(f"{prefix}/examples/alex/self.mem") == []
    assert module._check_member_name(
        f"{prefix}/tests/fixtures/phase_minus_one/baseline.mem"
    ) == []
    synthetic_entries = [
        (f"{prefix}/{suffix}", b"")
        for suffix in module.REQUIRED_PAPER_MEMBER_SUFFIXES
    ]
    assert module._missing_paper_members(synthetic_entries) == []
    assert module._missing_paper_members(synthetic_entries[:-1])
    for forbidden in (
        f"{prefix}/AGENTS.md",
        f"{prefix}/approved.mem",
        f"{prefix}/private/workspace.mem",
        f"{prefix}/.memdsl/audit.log",
        f"{prefix}/docs/launch_article_zh.md",
        f"{prefix}/.env.production",
        f"{prefix}/cache.sqlite3",
        f"{prefix}/private-review.xlsx",
        f"{prefix}/id_ed25519",
    ):
        assert module._check_member_name(forbidden), forbidden


def test_paper_metadata_and_frozen_evidence_contract() -> None:
    script = ROOT / "scripts" / "release_checks.py"
    spec = importlib.util.spec_from_file_location("release_checks_paper", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.check_paper(ROOT)
