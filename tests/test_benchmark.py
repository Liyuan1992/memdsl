import json
from pathlib import Path

import pytest

from memdsl.benchmark import (
    load_cases,
    render_benchmark_text,
    run_compliance_benchmark,
)
from memdsl.cli import main as cli_main
from memdsl.model import Workspace


ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "compliance"


def test_shipped_compliance_benchmark_passes():
    report = run_compliance_benchmark(
        Workspace.load([str(DEMO)]), load_cases(str(DEMO / "cases.jsonl")))
    assert report["status"] == "passed"
    assert report["passed"] == report["cases"] == 8
    assert report["modes"]["compliance_gate"]["metrics"]["verdict_accuracy"] == 1.0
    assert report["modes"]["no_memory"]["metrics"]["unsafe_allow_rate"] == 1.0
    assert "compliance_gate" in render_benchmark_text(report)


def test_cli_eval_compliance_json(capsys):
    code = cli_main([
        "eval", "compliance", str(DEMO),
        "--cases", str(DEMO / "cases.jsonl"), "--json",
    ])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "memdsl.compliance.benchmark.v1"
    assert payload["status"] == "passed"


def test_case_loader_rejects_bad_input(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"id":"x"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="missing required"):
        load_cases(str(path))
