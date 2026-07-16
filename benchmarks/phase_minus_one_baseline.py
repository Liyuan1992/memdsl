"""Reproducible synthetic scale baseline for the memdsl 0.6.0 read path.

This script never reads a memory workspace. It generates fictional declarations
in memory, parses them with the public 0.6.0 model, and measures the current MCP
map/query/explain payload builders at 100, 1,000, and 10,000 declarations.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gc
import hashlib
import json
import platform
import statistics
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from memdsl import __version__  # noqa: E402
from memdsl.mcp_service import MemdslMCPService  # noqa: E402
from memdsl.model import Workspace  # noqa: E402
from memdsl.parser import parse_text  # noqa: E402


BASELINE_SOURCE_COMMIT = "72274d9d4f065b76bceaf30f529dcbd47b3f3e18"
BASELINE_CHARACTERIZATION_COMMIT = "cf8c2bc0f1d338de0154c9c5129ad92c68279025"
EXPECTED_MEMDSL_VERSION = "0.6.0"
EXPECTED_RUNTIME_SOURCE_SHA256 = (
    "7bbbe6f17084128b5106472d5c4d8a194768d1db4d6280ca91371cc47807ca8c"
)
SCHEMA_VERSION = "memdsl.synthetic_scale_baseline.v1"


def canonical_source_digest(files: Iterable[Tuple[str, bytes]]) -> str:
    """Hash stable source names and bytes after normalizing CRLF to LF."""
    digest = hashlib.sha256()
    for relative, payload in sorted(files):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(payload.replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    return digest.hexdigest()


def runtime_source_digest(src_root: Path = SRC) -> str:
    """Hash the runtime source with platform-independent LF semantics."""
    files = (
        (path.relative_to(src_root).as_posix(), path.read_bytes())
        for path in (src_root / "memdsl").glob("*.py")
    )
    return canonical_source_digest(files)


def validate_runtime_identity(version: str, source_digest: str) -> None:
    """Reject measurements made with a runtime other than the frozen anchor."""
    if (
        version != EXPECTED_MEMDSL_VERSION
        or source_digest != EXPECTED_RUNTIME_SOURCE_SHA256
    ):
        raise RuntimeError(
            "phase-minus-one baseline requires the runtime source anchored at "
            f"{BASELINE_SOURCE_COMMIT}; use characterization commit "
            f"{BASELINE_CHARACTERIZATION_COMMIT}; loaded version={version} "
            f"source_sha256={source_digest}"
        )


def require_baseline_runtime() -> None:
    """Validate the loaded version and exact runtime source bytes."""
    validate_runtime_identity(__version__, runtime_source_digest())


def synthetic_source(declarations: int) -> str:
    """Build a deterministic, explicitly fictional source string."""
    if declarations < 1:
        raise ValueError("declarations must be positive")
    items = [
        '''module synthetic.scale

fact root.target {
  claim: "Synthetic beacon root target."
  scope: synthetic
  lifecycle { status: active }
  evidence { source: synthetic_generator quote: "Fictional root." }
}'''
    ]
    for index in range(1, declarations):
        items.append(f'''
fact item.{index:05d} {{
  claim: "Synthetic beacon item {index:05d}."
  scope: synthetic
  lifecycle {{ status: active }}
  relations {{ related_to: root.target }}
  evidence {{ source: synthetic_generator quote: "Fictional item {index:05d}." }}
}}''')
    return "\n".join(items) + "\n"


def parse_workspace(source: str, declarations: int) -> Workspace:
    ws = Workspace()
    ws.add_document(parse_text(
        source, file=f"<synthetic-scale-{declarations}.mem>"))
    return ws


def _measure(
    operation: Callable[[], object],
    repeats: int,
) -> Tuple[dict, object]:
    elapsed_ms: List[float] = []
    peak_mib: List[float] = []
    retained = None
    for _ in range(repeats):
        gc.collect()
        tracemalloc.start()
        started = time.perf_counter()
        result = operation()
        elapsed_ms.append((time.perf_counter() - started) * 1000.0)
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peak_mib.append(peak / (1024.0 * 1024.0))
        retained = result
        del result
    return {
        "elapsed_ms": [round(value, 3) for value in elapsed_ms],
        "peak_mib": [round(value, 3) for value in peak_mib],
        "median_elapsed_ms": round(statistics.median(elapsed_ms), 3),
        "min_elapsed_ms": round(min(elapsed_ms), 3),
        "max_elapsed_ms": round(max(elapsed_ms), 3),
        "median_peak_mib": round(statistics.median(peak_mib), 3),
    }, retained


def _json_bytes(payload: object) -> int:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return len(encoded)


def measure_size(declarations: int, repeats: int) -> dict:
    source = synthetic_source(declarations)
    parse_stats, parsed = _measure(
        lambda: parse_workspace(source, declarations), repeats)
    assert isinstance(parsed, Workspace)
    ws = parsed

    service = MemdslMCPService([str(Path(__file__).resolve().parent)])
    service.workspace = lambda: ws  # type: ignore[method-assign]

    map_stats, map_payload = _measure(service.memory_map, repeats)
    query_stats, query_payload = _measure(
        lambda: service.query("synthetic beacon", limit=8), repeats)
    explain_stats, explain_payload = _measure(
        lambda: service.explain("fact:root.target"), repeats)

    return {
        "declarations": declarations,
        "source_bytes": len(source.encode("utf-8")),
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "parse": parse_stats,
        "map": {
            **map_stats,
            "payload_bytes": _json_bytes(map_payload),
            "returned_declarations": map_payload["declarations"],
        },
        "query": {
            **query_stats,
            "payload_bytes": _json_bytes(query_payload),
            "returned_context": len(
                query_payload["evidence_pack"]["context"]),
            "candidates_considered": query_payload[
                "evidence_pack"]["search_trace"]["candidates_considered"],
        },
        "explain": {
            **explain_stats,
            "payload_bytes": _json_bytes(explain_payload),
            "incoming_references": len(
                explain_payload["declaration"]["referenced_by"]),
        },
    }


def run(sizes: Sequence[int], repeats: int) -> dict:
    require_baseline_runtime()
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "baseline": {
            "memdsl_version": __version__,
            "source_commit": BASELINE_SOURCE_COMMIT,
            "runtime_semantics": "unmodified memdsl 0.6.0",
        },
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "method": {
            "fixture": "deterministic in-memory fictional .mem source",
            "workspace_reads": 0,
            "repeats": repeats,
            "timing": "time.perf_counter wall time per operation",
            "memory": "tracemalloc peak allocated bytes per operation",
            "payload": "compact sorted UTF-8 JSON bytes of the current MCP payload",
            "query": "synthetic beacon",
            "query_limit": 8,
            "explain_id": "fact:root.target",
        },
        "results": [measure_size(size, repeats) for size in sizes],
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sizes",
        nargs="+",
        type=int,
        default=[100, 1000, 10000],
        help="declaration counts to generate",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=5,
        help="measured repetitions per operation",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="optional JSON output path; stdout is always emitted",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.repeats < 1:
        raise SystemExit("--repeats must be positive")
    if any(size < 1 for size in args.sizes):
        raise SystemExit("all --sizes values must be positive")
    report = run(args.sizes, args.repeats)
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
