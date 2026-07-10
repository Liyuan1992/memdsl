"""Reproducible boundary-compliance benchmark runner."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List

from memdsl.compliance import check_compliance
from memdsl.model import Workspace
from memdsl.query import build_evidence_pack


BENCHMARK_SCHEMA = "memdsl.compliance.benchmark.v1"
MODES = ("no_memory", "flat_context", "evidence_pack", "compliance_gate")
_WORD_RE = re.compile(r"[a-z0-9_]+")


@dataclass
class ComplianceCase:
    id: str
    task: str
    candidate: str
    expected_verdict: str
    expected_must: List[str]
    expected_violations: List[str]
    expected_exceptions: List[str]
    subject: str = ""
    scope: str = ""
    exceptions: List[str] = None

    def __post_init__(self) -> None:
        if self.exceptions is None:
            self.exceptions = []


def load_cases(path: str) -> List[ComplianceCase]:
    cases: List[ComplianceCase] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            try:
                raw = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            required = ("id", "task", "candidate", "expected_verdict")
            missing = [key for key in required if not str(raw.get(key, "")).strip()]
            if missing:
                raise ValueError(
                    f"{path}:{line_no}: missing required field(s): {', '.join(missing)}")
            verdict = str(raw["expected_verdict"])
            if verdict not in ("allow", "block", "needs_review"):
                raise ValueError(
                    f"{path}:{line_no}: invalid expected_verdict {verdict!r}")
            cases.append(ComplianceCase(
                id=str(raw["id"]),
                task=str(raw["task"]),
                candidate=str(raw["candidate"]),
                expected_verdict=verdict,
                expected_must=[str(x) for x in raw.get("expected_must", [])],
                expected_violations=[str(x) for x in raw.get("expected_violations", [])],
                expected_exceptions=[str(x) for x in raw.get("expected_exceptions", [])],
                subject=str(raw.get("subject", "")),
                scope=str(raw.get("scope", "")),
                exceptions=[str(x) for x in raw.get("exceptions", [])],
            ))
    if not cases:
        raise ValueError(f"{path}: no benchmark cases found")
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: duplicate case ids")
    return cases


def _terms(text: str) -> set:
    return set(_WORD_RE.findall(text.lower()))


def _flat_context_prediction(ws: Workspace, case: ComplianceCase) -> dict:
    query_terms = _terms(case.task + " " + case.candidate)
    ids = []
    superseded = ws.superseded_ids()
    for decl in ws.active():
        if decl.kind != "boundary":
            continue
        if decl.id in superseded or decl.name in superseded:
            continue
        if query_terms & _terms(decl.searchable_text()):
            ids.append(decl.id)
    return {
        "verdict": "needs_review" if ids else "allow",
        "applicable_must": sorted(ids),
        "violations": [],
        "exceptions_applied": [],
    }


def _prediction(ws: Workspace, case: ComplianceCase, mode: str) -> dict:
    if mode == "no_memory":
        return {
            "verdict": "allow",
            "applicable_must": [],
            "violations": [],
            "exceptions_applied": [],
        }
    if mode == "flat_context":
        return _flat_context_prediction(ws, case)
    if mode == "evidence_pack":
        evidence = build_evidence_pack(
            ws, case.task + "\n" + case.candidate,
            subject=case.subject or None, limit=100)
        ids = [d.id for d in evidence.must]
        return {
            "verdict": "needs_review" if ids else "allow",
            "applicable_must": ids,
            "violations": [],
            "exceptions_applied": [],
        }
    if mode == "compliance_gate":
        pack = check_compliance(
            ws, case.task, case.candidate,
            subject=case.subject or None,
            scope=case.scope or None,
            exceptions=case.exceptions,
        ).as_dict()
        return {
            "verdict": pack["verdict"],
            "applicable_must": [d["id"] for d in pack["applicable_must"]],
            "violations": [v["boundary_id"] for v in pack["violations"]],
            "exceptions_applied": [
                item["boundary_id"] for item in pack["exceptions_applied"]],
        }
    raise ValueError(f"unknown benchmark mode: {mode}")


def _summarize(rows: Iterable[dict]) -> dict:
    items = list(rows)
    total = len(items)
    expected_blocks = sum(1 for row in items if row["expected_verdict"] == "block")
    expected_nonblocks = total - expected_blocks
    expected_boundaries = sum(len(row["expected_must"]) for row in items)
    boundary_hits = sum(
        len(set(row["expected_must"]) & set(row["applicable_must"]))
        for row in items)
    citations = sum(len(row["violations"]) for row in items)
    valid_citations = sum(
        len(set(row["violations"]) & set(row["applicable_must"]))
        for row in items)
    return {
        "cases": total,
        "verdict_accuracy": round(
            sum(row["verdict"] == row["expected_verdict"] for row in items) / total, 4),
        "unsafe_allow_rate": round(
            sum(
                row["expected_verdict"] == "block" and row["verdict"] == "allow"
                for row in items) / expected_blocks, 4) if expected_blocks else 0.0,
        "false_block_rate": round(
            sum(
                row["expected_verdict"] != "block" and row["verdict"] == "block"
                for row in items) / expected_nonblocks, 4) if expected_nonblocks else 0.0,
        "boundary_recall": round(
            boundary_hits / expected_boundaries, 4) if expected_boundaries else 1.0,
        "citation_accuracy": round(
            valid_citations / citations, 4) if citations else 1.0,
    }


def run_compliance_benchmark(
    ws: Workspace, cases: Iterable[ComplianceCase]) -> dict:
    case_list = list(cases)
    mode_payloads: Dict[str, dict] = {}
    for mode in MODES:
        rows = []
        for case in case_list:
            predicted = _prediction(ws, case, mode)
            row = {
                "id": case.id,
                "expected_verdict": case.expected_verdict,
                "expected_must": case.expected_must,
                "expected_violations": case.expected_violations,
                "expected_exceptions": case.expected_exceptions,
                **predicted,
            }
            row["passed"] = (
                row["verdict"] == case.expected_verdict
                and set(case.expected_must).issubset(row["applicable_must"])
                and set(row["violations"]) == set(case.expected_violations)
                and set(row["exceptions_applied"]) == set(case.expected_exceptions)
            )
            rows.append(row)
        mode_payloads[mode] = {
            "metrics": _summarize(rows),
            "cases": rows,
        }
    compliance_rows = mode_payloads["compliance_gate"]["cases"]
    passed = sum(1 for row in compliance_rows if row["passed"])
    return {
        "schema_version": BENCHMARK_SCHEMA,
        "status": "passed" if passed == len(compliance_rows) else "failed",
        "cases": len(compliance_rows),
        "passed": passed,
        "modes": mode_payloads,
    }


def render_benchmark_text(report: dict) -> str:
    lines = [
        f"boundary-compliance benchmark: {report['status'].upper()} "
        f"({report['passed']}/{report['cases']} compliance cases)",
        "",
        "MODE              VERDICT  UNSAFE_ALLOW  FALSE_BLOCK  MUST_RECALL",
    ]
    for mode in MODES:
        metrics = report["modes"][mode]["metrics"]
        lines.append(
            f"{mode:17} "
            f"{metrics['verdict_accuracy']:.3f}    "
            f"{metrics['unsafe_allow_rate']:.3f}         "
            f"{metrics['false_block_rate']:.3f}        "
            f"{metrics['boundary_recall']:.3f}")
    failed = [
        row for row in report["modes"]["compliance_gate"]["cases"]
        if not row["passed"]
    ]
    if failed:
        lines.extend(["", "FAILED CASES"])
        for row in failed:
            lines.append(
                f"- {row['id']}: expected {row['expected_verdict']}, "
                f"got {row['verdict']}")
    return "\n".join(lines)
