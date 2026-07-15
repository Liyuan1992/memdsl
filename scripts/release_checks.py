"""Deterministic source and artifact checks for a memdsl release candidate."""

from __future__ import annotations

import argparse
import ast
import hashlib
import os
import re
import subprocess
import sys
import tarfile
import zipfile
from importlib import metadata
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


TEXT_SUFFIXES = {
    ".cfg",
    ".ini",
    ".json",
    ".md",
    ".mem",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}

FORBIDDEN_BASENAMES = {
    ".env",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "agents.md",
    "approved.mem",
    "credentials.json",
    "id_ed25519",
    "id_rsa",
    "launch_article_zh.md",
    "secrets.json",
}

FORBIDDEN_SEGMENTS = {
    ".memdsl",
    ".pytest_cache",
    "__pycache__",
}

FORBIDDEN_SUFFIXES = {
    ".bak",
    ".backup",
    ".db",
    ".key",
    ".log",
    ".p12",
    ".pem",
    ".pfx",
    ".sqlite",
    ".sqlite3",
    ".ods",
    ".xls",
    ".xlsm",
    ".xlsx",
}

RELEASE_SOURCE_DATE_EPOCH = 1784077269
RELEASE_HATCHLING_VERSION = "1.31.0"
EXPECTED_PAPER_WORDS = 5250

REQUIRED_PAPER_MEMBER_SUFFIXES = {
    "CITATION.cff",
    "LICENSE",
    "DOCUMENTATION_INDEX.md",
    "DESIGN_memory_source_compiled_view.md",
    "DESIGN_explicit_edges_phase6.md",
    "PAPER_LICENSE.md",
    "PAPER_publication_readiness_audit.md",
    "PAPER_related_work_claim_ledger.md",
    "PAPER_reproducibility_and_release_metadata.md",
    "PAPER_review_gated_authority_source_compiled_contract.md",
    "PUBLIC_API.md",
    "RELEASE_SCOPE_PHASE6.md",
    "SPEC.md",
    "UPGRADING.md",
    "baselines/PHASE_MINUS_ONE_SCALE_BASELINE.md",
    "baselines/phase_minus_one_0.6.0.json",
    "benchmarks/phase_minus_one_baseline.py",
}

PAPER_FROZEN_BLOB_HASHES = {
    "CITATION.cff": "10d97f3146253555f06b52edc85dcf45053f39c55a3530ac55e060eca7a97499",
    "docs/PAPER_publication_readiness_audit.md": "c4a2cfad7e6462abeffb0b38615cc2511cf5a7a5e8910c51599908737af6e837",
    "docs/PAPER_related_work_claim_ledger.md": "0704562e6a7631e78ec369970e65f591563c42289b8746eb96c9dd1ee134190c",
    "docs/PAPER_reproducibility_and_release_metadata.md": "083ef73a0d99d5dec8ca0969bc1753faea2f5a7de4951009901be1c5f7a90c30",
    "docs/PAPER_review_gated_authority_source_compiled_contract.md": "133d489ed6d8bc016de246cbf87f33dc083d09d7b9092a11456ae3c736317a45",
}

FROZEN_BASELINE_HASHES = {
    "docs/baselines/phase_minus_one_0.6.0.json": "fad66899ce0e795efdbd0d3691d24d4b85414f4627c75d06abe826e165dbeca8",
    "docs/baselines/PHASE_MINUS_ONE_SCALE_BASELINE.md": "acb80fb9413f58944597b9f71b4f8e5ff71dd4a94ca91479c12982cb226c855d",
    "benchmarks/phase_minus_one_baseline.py": "6d37c9f3eb55e35e8a8a7e40d6cd20bc59654b6d3f2d7d822c2b9d2a1b25b574",
}

PAPER_MARKDOWN_FILES = {
    "README.md",
    "docs/DOCUMENTATION_INDEX.md",
    "docs/DESIGN_memory_source_compiled_view.md",
    "docs/DESIGN_explicit_edges_phase6.md",
    "docs/PAPER_LICENSE.md",
    "docs/PAPER_publication_readiness_audit.md",
    "docs/PAPER_related_work_claim_ledger.md",
    "docs/PAPER_reproducibility_and_release_metadata.md",
    "docs/PAPER_review_gated_authority_source_compiled_contract.md",
    "docs/PUBLIC_API.md",
    "docs/RELEASE_SCOPE_PHASE6.md",
    "docs/SPEC.md",
    "docs/UPGRADING.md",
}


def _read_declared_version(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"\s*$', text, re.MULTILINE)
    if not match:
        raise AssertionError(f"project version not found in {path}")
    return match.group(1)


def _read_runtime_version(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"\s*$', text, re.MULTILINE)
    if not match:
        raise AssertionError(f"runtime version not found in {path}")
    return match.group(1)


def check_version(repo_root: Path, expected: Optional[str]) -> None:
    declared = _read_declared_version(repo_root / "pyproject.toml")
    runtime = _read_runtime_version(repo_root / "src" / "memdsl" / "__init__.py")
    if declared != runtime:
        raise AssertionError(
            f"pyproject version {declared!r} != runtime version {runtime!r}"
        )
    if expected is not None and declared != expected:
        raise AssertionError(f"expected version {expected!r}, found {declared!r}")
    print(f"version={declared}")


def check_python39_ast(repo_root: Path) -> None:
    source_files = sorted((repo_root / "src" / "memdsl").rglob("*.py"))
    if not source_files:
        raise AssertionError("no core source files found")
    for path in source_files:
        ast.parse(
            path.read_text(encoding="utf-8"),
            filename=str(path),
            feature_version=(3, 9),
        )
    print(f"python39_ast_files={len(source_files)}")


def check_source_date_epoch() -> None:
    raw = os.environ.get("SOURCE_DATE_EPOCH", "")
    if not raw.isdigit():
        raise AssertionError("SOURCE_DATE_EPOCH must be a positive integer")
    value = int(raw)
    if value != RELEASE_SOURCE_DATE_EPOCH:
        raise AssertionError(
            f"SOURCE_DATE_EPOCH {value} != frozen {RELEASE_SOURCE_DATE_EPOCH}"
        )
    print(f"source_date_epoch={value}")


def _git_stdout(repo_root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise AssertionError(f"git {' '.join(args)} failed: {stderr.strip()}")
    return result.stdout


def check_source_tree(repo_root: Path) -> None:
    """Verify canonical checkout bytes and print a path-independent digest."""

    tracked = [
        item.decode("utf-8")
        for item in _git_stdout(repo_root, "ls-files", "-z").split(b"\0")
        if item
    ]
    if not tracked:
        raise AssertionError("no tracked source files found")
    if "docs/launch_article_zh.md" in {item.lower() for item in tracked}:
        raise AssertionError("protected launch article must not be tracked")

    failures: List[str] = []
    lf_files = 0
    crlf_files = 0
    binary_files = 0
    records = _git_stdout(repo_root, "ls-files", "--eol", "-z")
    for raw_record in records.split(b"\0"):
        if not raw_record:
            continue
        record = raw_record.decode("utf-8")
        if "\t" not in record:
            failures.append(f"unrecognized git eol record: {record!r}")
            continue
        eol_fields, relative = record.split("\t", 1)
        match = re.match(
            r"^i/(\S+)\s+w/(\S+)\s+attr/(.*)$", eol_fields.strip()
        )
        if match is None:
            failures.append(f"unrecognized git eol metadata for {relative}")
            continue
        index_eol, worktree_eol, attributes = match.groups()
        if index_eol == "-text" or worktree_eol == "-text":
            binary_files += 1
            continue
        if index_eol not in {"lf", "none"}:
            failures.append(f"{relative}: Git index uses {index_eol}, expected LF")
        if "eol=crlf" in attributes:
            crlf_files += 1
            if worktree_eol not in {"crlf", "none"}:
                failures.append(
                    f"{relative}: worktree uses {worktree_eol}, expected CRLF"
                )
            continue
        lf_files += 1
        if "eol=lf" not in attributes:
            failures.append(f"{relative}: missing repository eol=lf contract")
        if worktree_eol not in {"lf", "none"}:
            failures.append(f"{relative}: worktree uses {worktree_eol}, expected LF")

    digest = hashlib.sha256()
    total_bytes = 0
    for relative in tracked:
        path = repo_root.joinpath(*relative.split("/"))
        if not path.is_file():
            failures.append(f"tracked source is not a regular file: {relative}")
            continue
        payload = path.read_bytes()
        encoded_path = relative.encode("utf-8")
        digest.update(len(encoded_path).to_bytes(4, "big"))
        digest.update(encoded_path)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
        total_bytes += len(payload)

    if failures:
        raise AssertionError("source tree checks failed:\n- " + "\n- ".join(failures))
    print(f"source_files={len(tracked)}")
    print(f"source_bytes={total_bytes}")
    print(f"source_sha256={digest.hexdigest()}")
    print(f"source_line_endings=lf:{lf_files},crlf:{crlf_files},binary:{binary_files}")


def check_build_toolchain(repo_root: Path) -> None:
    """Verify the exact backend that produces wheel and sdist bytes."""

    pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    exact_requirement = f'hatchling=={RELEASE_HATCHLING_VERSION}'
    if pyproject.count(f'"{exact_requirement}"') != 2:
        raise AssertionError(
            f"pyproject.toml must pin {exact_requirement} in build-system and dev"
        )
    try:
        installed = metadata.version("hatchling")
    except metadata.PackageNotFoundError as exc:
        raise AssertionError("hatchling is not installed in the release environment") from exc
    if installed != RELEASE_HATCHLING_VERSION:
        raise AssertionError(
            f"hatchling {installed} != frozen {RELEASE_HATCHLING_VERSION}"
        )
    print(f"hatchling={installed}")
    try:
        print(f"build_frontend={metadata.version('build')}")
    except metadata.PackageNotFoundError:
        print("build_frontend=not-installed")
    print("artifact_byte_producer=hatchling")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_normalized_text(path: Path) -> str:
    payload = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(payload).hexdigest()


def _check_markdown_links(repo_root: Path, paths: Iterable[str]) -> List[str]:
    failures: List[str] = []
    link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    for relative in sorted(paths):
        path = repo_root / relative
        text = path.read_text(encoding="utf-8")
        for raw_target in link_pattern.findall(text):
            target = raw_target.strip().split()[0].strip("<>")
            if (
                not target
                or target.startswith("#")
                or target.startswith("http://")
                or target.startswith("https://")
                or target.startswith("mailto:")
            ):
                continue
            target_path = target.split("#", 1)[0]
            if not target_path:
                continue
            resolved = (path.parent / target_path).resolve()
            if not resolved.exists():
                failures.append(f"{relative}: missing link target {target}")
    return failures


def check_paper(repo_root: Path) -> None:
    failures: List[str] = []
    required_paths = (
        set(PAPER_FROZEN_BLOB_HASHES)
        | set(FROZEN_BASELINE_HASHES)
        | PAPER_MARKDOWN_FILES
        | {"LICENSE", "pyproject.toml"}
    )
    for relative in sorted(required_paths):
        if not (repo_root / relative).is_file():
            failures.append(f"missing paper/release file: {relative}")

    if failures:
        raise AssertionError("paper checks failed:\n- " + "\n- ".join(failures))

    for relative, expected in PAPER_FROZEN_BLOB_HASHES.items():
        actual = _sha256_normalized_text(repo_root / relative)
        if actual != expected:
            failures.append(f"{relative}: sha256 {actual} != {expected}")
    for relative, expected in FROZEN_BASELINE_HASHES.items():
        actual = _sha256(repo_root / relative)
        if actual != expected:
            failures.append(f"{relative}: sha256 {actual} != {expected}")

    manuscript = (
        repo_root / "docs/PAPER_review_gated_authority_source_compiled_contract.md"
    ).read_text(encoding="utf-8")
    body, references = manuscript.split("## References", 1)
    reference_numbers = set(re.findall(r"^\[(\d+)\] ", references, re.MULTILINE))
    cited_numbers = {
        number
        for citation_group in re.findall(r"\[([0-9,\s]+)\]", body)
        for number in re.findall(r"\d+", citation_group)
    }
    expected_references = {str(index) for index in range(1, 15)}
    if reference_numbers != expected_references:
        failures.append(
            f"manuscript reference entries={sorted(reference_numbers)} expected=1..14"
        )
    if not expected_references <= cited_numbers:
        failures.append(
            "manuscript body missing citations: "
            + ", ".join(sorted(expected_references - cited_numbers))
        )
    manuscript_words = len(re.findall(r"\S+", manuscript))
    if manuscript_words != EXPECTED_PAPER_WORDS:
        failures.append(
            f"manuscript whitespace words={manuscript_words} "
            f"expected={EXPECTED_PAPER_WORDS}"
        )

    ledger = (repo_root / "docs/PAPER_related_work_claim_ledger.md").read_text(
        encoding="utf-8"
    )
    claim_ids = re.findall(
        r"^\| ((?:A|I|RW|CB|C)-\d{2}) \|", ledger, re.MULTILINE
    )
    if len(claim_ids) != 24 or len(set(claim_ids)) != 24:
        failures.append(
            f"claim ledger rows={len(claim_ids)} unique={len(set(claim_ids))} expected=24"
        )

    release_scope = (repo_root / "docs/RELEASE_SCOPE_PHASE6.md").read_text(
        encoding="utf-8"
    )
    for required in (
        "Stable/public",
        "Experimental",
        "Planned / not shipped",
        "Host-specific / excluded",
        "accept=7",
        "uncertain=3",
        "reject=0",
        "relation_edge_event",
        "edge_lifecycle",
        "Exact-commit build contract",
        "Hatchling `1.31.0`",
        "release_checks.py source-tree",
        "python -m build --no-isolation",
        "4ee810833ef0cbd8562e72e3ad202a07c5ce77e8",
        "6bc3ffd986b1ffe29cefa928642fd0cf47e5c2c9",
        "4ec9d43fda56a277609dd822c61acdb9a7265655",
    ):
        if required not in release_scope:
            failures.append(f"RELEASE_SCOPE_PHASE6.md missing contract text: {required}")
    citation = (repo_root / "CITATION.cff").read_text(encoding="utf-8")
    for required in (
        "cff-version: 1.2.0",
        'version: "0.6.0"',
        "commit: 72274d9d4f065b76bceaf30f529dcbd47b3f3e18",
        "preferred-citation:",
        '  version: "0.6"',
        "  license: CC-BY-4.0",
    ):
        if required not in citation:
            failures.append(f"CITATION.cff missing contract text: {required}")

    paper_license = (repo_root / "docs/PAPER_LICENSE.md").read_text(encoding="utf-8")
    for name in (
        "PAPER_review_gated_authority_source_compiled_contract.md",
        "PAPER_related_work_claim_ledger.md",
        "PAPER_reproducibility_and_release_metadata.md",
        "PAPER_publication_readiness_audit.md",
        "PAPER_final_integration_audit.md",
    ):
        if name not in paper_license:
            failures.append(f"PAPER_LICENSE.md does not cover {name}")

    root_license = (repo_root / "LICENSE").read_text(encoding="utf-8")
    if "final local integration audit" not in root_license:
        failures.append("LICENSE does not preserve the software/paper license split")

    pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    for suffix in REQUIRED_PAPER_MEMBER_SUFFIXES:
        basename = Path(suffix).name
        if basename not in pyproject:
            failures.append(f"pyproject.toml does not package {basename}")
    for excluded in ("/AGENTS.md", "/docs/PAPER_final_integration_audit.md"):
        if f'"{excluded}"' not in pyproject:
            failures.append(f"pyproject.toml does not exclude {excluded}")

    failures.extend(_check_markdown_links(repo_root, PAPER_MARKDOWN_FILES))

    privacy_paths = set(PAPER_MARKDOWN_FILES) | {"CITATION.cff", "LICENSE"}
    integration_audit = repo_root / "docs/PAPER_final_integration_audit.md"
    if integration_audit.is_file():
        privacy_paths.add("docs/PAPER_final_integration_audit.md")
    patterns = _privacy_patterns(repo_root)
    for relative in sorted(privacy_paths):
        text = (repo_root / relative).read_text(encoding="utf-8")
        for label, pattern in patterns.items():
            if pattern.search(text):
                failures.append(f"{relative}: matched privacy pattern {label}")

    if failures:
        raise AssertionError("paper checks failed:\n- " + "\n- ".join(failures))
    print("paper_references=14")
    print("paper_claim_rows=24")
    print(f"paper_words={manuscript_words}")
    print("paper_links=ok")
    print("paper_license=ok")
    print("paper_privacy=ok")
    print("paper_frozen_hashes=ok")


def _archive_entries(path: Path) -> List[Tuple[str, bytes]]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return [
                (name, archive.read(name))
                for name in sorted(archive.namelist())
                if not name.endswith("/")
            ]
    with tarfile.open(path, "r:gz") as archive:
        entries: List[Tuple[str, bytes]] = []
        for member in sorted(archive.getmembers(), key=lambda item: item.name):
            if not member.isfile():
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                raise AssertionError(f"could not read {member.name} from {path}")
            entries.append((member.name, extracted.read()))
        return entries


def _relative_member(name: str) -> str:
    normalized = name.replace("\\", "/").lstrip("./")
    parts = normalized.split("/")
    if parts and parts[0].startswith("memdsl-"):
        parts = parts[1:]
    return "/".join(parts)


def _metadata_version(entries: Iterable[Tuple[str, bytes]], suffix: str) -> str:
    matches = [payload for name, payload in entries if name.endswith(suffix)]
    if len(matches) != 1:
        raise AssertionError(f"expected one {suffix} metadata member, found {len(matches)}")
    text = matches[0].decode("utf-8")
    match = re.search(r"^Version:\s*(\S+)\s*$", text, re.MULTILINE)
    if not match:
        raise AssertionError(f"Version field missing from {suffix}")
    return match.group(1)


def _privacy_patterns(repo_root: Path) -> Dict[str, re.Pattern[str]]:
    private_key = "-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    patterns = {
        "windows_absolute_path": re.compile(r"(?<![A-Za-z0-9+.-])[A-Za-z]:[\\/]"),
        "unix_home_path": re.compile(r"/(?:home|Users)/[^/\s]+/"),
        "private_key": re.compile(private_key),
        "aws_access_key": re.compile(r"AKIA[0-9A-Z]{16}"),
        "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
        "openai_token": re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    }
    root_text = str(repo_root.resolve())
    patterns["build_workspace_path"] = re.compile(
        re.escape(root_text), re.IGNORECASE
    )
    return patterns


def _check_member_name(name: str) -> List[str]:
    relative = _relative_member(name)
    lowered = relative.lower()
    path = Path(relative)
    failures: List[str] = []
    parts = {part.lower() for part in path.parts}
    basename = path.name.lower()
    suffix = path.suffix.lower()

    if basename in FORBIDDEN_BASENAMES:
        failures.append(f"forbidden member basename: {relative}")
    if basename.startswith(".env."):
        failures.append(f"forbidden environment file: {relative}")
    if parts & FORBIDDEN_SEGMENTS:
        failures.append(f"forbidden generated/runtime member: {relative}")
    if suffix in FORBIDDEN_SUFFIXES:
        failures.append(f"forbidden sensitive/runtime suffix: {relative}")
    if lowered.endswith("docs/launch_article_zh.md"):
        failures.append(f"private checkout-only document included: {relative}")
    if suffix == ".mem" and not (
        lowered.startswith("examples/") or lowered.startswith("tests/fixtures/")
    ):
        failures.append(f"memory source outside synthetic fixture roots: {relative}")
    return failures


def _missing_paper_members(entries: Iterable[Tuple[str, bytes]]) -> List[str]:
    relative_names = [_relative_member(name) for name, _ in entries]
    return sorted(
        suffix
        for suffix in REQUIRED_PAPER_MEMBER_SUFFIXES
        if not any(name.endswith(suffix) for name in relative_names)
    )


def check_artifacts(repo_root: Path, dist_dir: Path, expected: str) -> None:
    wheels = sorted(dist_dir.glob(f"memdsl-{expected}-*.whl"))
    sdists = sorted(dist_dir.glob(f"memdsl-{expected}.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise AssertionError(
            f"expected one wheel and one sdist for {expected}; "
            f"found wheels={len(wheels)} sdists={len(sdists)}"
        )

    failures: List[str] = []
    patterns = _privacy_patterns(repo_root)
    for artifact in [wheels[0], sdists[0]]:
        entries = _archive_entries(artifact)
        metadata_suffix = ".dist-info/METADATA" if artifact.suffix == ".whl" else "/PKG-INFO"
        metadata_version = _metadata_version(entries, metadata_suffix)
        if metadata_version != expected:
            failures.append(
                f"{artifact.name}: metadata version {metadata_version!r} != {expected!r}"
            )

        missing_paper_members = _missing_paper_members(entries)
        if missing_paper_members:
            failures.append(
                f"{artifact.name}: missing required paper members: "
                + ", ".join(missing_paper_members)
            )

        print(f"artifact={artifact.name} members={len(entries)}")
        for name, payload in entries:
            print(f"  {name}")
            failures.extend(
                f"{artifact.name}: {failure}" for failure in _check_member_name(name)
            )
            if Path(name).suffix.lower() not in TEXT_SUFFIXES:
                continue
            text = payload.decode("utf-8", errors="ignore")
            for label, pattern in patterns.items():
                if pattern.search(text):
                    failures.append(
                        f"{artifact.name}: {name}: matched privacy pattern {label}"
                    )

    if failures:
        raise AssertionError("artifact privacy check failed:\n- " + "\n- ".join(failures))
    print("artifact_privacy=ok")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)

    version = subparsers.add_parser("version")
    version.add_argument("--expected")

    subparsers.add_parser("python39-ast")

    subparsers.add_parser("source-date-epoch")

    subparsers.add_parser("source-tree")

    subparsers.add_parser("build-toolchain")

    subparsers.add_parser("paper")

    artifacts = subparsers.add_parser("artifacts")
    artifacts.add_argument("--dist", type=Path, default=Path("dist"))
    artifacts.add_argument("--expected", required=True)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    if args.command == "version":
        check_version(repo_root, args.expected)
    elif args.command == "python39-ast":
        check_python39_ast(repo_root)
    elif args.command == "source-date-epoch":
        check_source_date_epoch()
    elif args.command == "source-tree":
        check_source_tree(repo_root)
    elif args.command == "build-toolchain":
        check_build_toolchain(repo_root)
    elif args.command == "paper":
        check_paper(repo_root)
    elif args.command == "artifacts":
        dist_dir = args.dist
        if not dist_dir.is_absolute():
            dist_dir = repo_root / dist_dir
        check_artifacts(repo_root, dist_dir.resolve(), args.expected)
    else:  # pragma: no cover
        raise AssertionError(args.command)
    return 0


if __name__ == "__main__":
    sys.exit(main())
