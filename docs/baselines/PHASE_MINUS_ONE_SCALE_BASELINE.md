# Phase -1 synthetic scale baseline (memdsl 0.6.0)

This baseline freezes measurement method and observed 0.6.0 behavior without
changing runtime semantics. It uses only deterministic, fictional declarations
generated in memory. It does not read an existing memory workspace and does not
create a `.memdsl` review store.

Raw results: [phase_minus_one_0.6.0.json](phase_minus_one_0.6.0.json)

## Reproduction

From the repository root with the development environment installed:

```console
.venv\Scripts\python.exe benchmarks\phase_minus_one_baseline.py \
  --sizes 100 1000 10000 \
  --repeats 5 \
  --output docs\baselines\phase_minus_one_0.6.0.json
```

POSIX environments may substitute `.venv/bin/python`.

The generator creates one active `fact:root.target` and `N - 1` active facts
with fictional evidence and an explicit `related_to: root.target` relation.
All declarations contain the query terms `synthetic beacon`. The benchmark
measures:

- parse: `parse_text()` plus `Workspace.add_document()`;
- map: the current MCP `memory_map` payload, including structured modules and
  `rendered_text`;
- query: the current MCP `memory_query` payload with `limit=8`, including the
  EvidencePack and `rendered_text`;
- explain: the current MCP `memory_explain` payload for the root, including all
  incoming references, evidence, fields, and `rendered_text`.

Wall time uses `time.perf_counter`. Peak allocated memory uses `tracemalloc`.
Each table value is the median of five measured repetitions; the raw JSON also
keeps every timing and peak sample. Payload bytes are compact, sorted UTF-8 JSON
bytes of the returned MCP-shaped payload.

## Recorded environment

- memdsl: 0.6.0, source baseline `72274d9d4f065b76bceaf30f529dcbd47b3f3e18`
- Python: CPython 3.12.10
- OS: Windows 11, AMD64
- Recorded: 2026-07-14

These are characterization numbers, not a performance promise. `tracemalloc`
adds instrumentation overhead, so comparisons should reuse the same script,
Python version, and measurement posture.

## Results

| Declarations | Source bytes | Parse ms / peak MiB | Map ms / peak MiB / bytes | Query ms / peak MiB / bytes / candidates | Explain ms / peak MiB / bytes / incoming |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 100 | 22,479 | 29.349 / 0.478 | 2.215 / 0.081 / 31,478 | 2.625 / 0.045 / 5,783 / 100 | 1.678 / 0.040 / 10,157 / 99 |
| 1,000 | 224,979 | 315.578 / 4.739 | 25.752 / 0.784 / 307,783 | 25.930 / 0.392 / 5,792 / 1,000 | 18.049 / 0.373 / 92,059 / 999 |
| 10,000 | 2,249,979 | 3,348.264 / 47.162 | 275.769 / 7.813 / 3,070,788 | 296.163 / 3.846 / 5,801 / 10,000 | 202.175 / 3.703 / 911,061 / 9,999 |

## What the baseline demonstrates

- Full parse time and peak allocations grow approximately with declaration
  count for this uniform synthetic source.
- `memory_map` returns every current map item twice in different
  representations and grows from 31,478 bytes at 100 declarations to
  3,070,788 bytes at 10,000 declarations.
- Query output remains near 5.8 KB because `limit=8`, but current candidate
  selection still considers all 100, 1,000, or 10,000 declarations and median
  latency grows from 2.625 ms to 296.163 ms under the recorded instrumentation.
- Explain returns all incoming references without pagination or a byte budget;
  its payload grows from 10,157 bytes for 99 incoming references to 911,061
  bytes for 9,999 incoming references.

The results justify later indexed and bounded projections. They do not authorize
CompiledWorkspace, Catalog, pagination, Trace, quarantine, or any serving
semantic change in Phase -1.
