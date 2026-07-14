"""Deterministic source and artifact checks for a memdsl release candidate."""

from __future__ import annotations

import argparse
import ast
import hashlib
import re
import sys
import tarfile
import zipfile
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

REQUIRED_PAPER_MEMBER_SUFFIXES = {
    "CITATION.cff",
    "LICENSE",
    "DOCUMENTATION_INDEX.md",
    "DESIGN_memory_source_compiled_view.md",
    "PAPER_LICENSE.md",
    "PAPER_publication_readiness_audit.md",
    "PAPER_related_work_claim_ledger.md",
    "PAPER_reproducibility_and_release_metadata.md",
    "PAPER_review_gated_authority_source_compiled_contract.md",
    "baselines/PHASE_MINUS_ONE_SCALE_BASELINE.md",
    "baselines/phase_minus_one_0.6.0.json",
    "benchmarks/phase_minus_one_baseline.py",
}

P5_FROZEN_BLOB_HASHES = {
    "CITATION.cff": "10d97f3146253555f06b52edc85dcf45053f39c55a3530ac55e060eca7a97499",
    "docs/PAPER_publication_readiness_audit.md": "8543e2ad3c3323be0d28360b7610ee751d4d273e64a2ecfa39553c093d13033e",
    "docs/PAPER_related_work_claim_ledger.md": "0704562e6a7631e78ec369970e65f591563c42289b8746eb96c9dd1ee134190c",
    "docs/PAPER_reproducibility_and_release_metadata.md": "3ac7b40dbcc4801bcf53f02ed14300297e94c27891e0c16719dc331c46c28043",
    "docs/PAPER_review_gated_authority_source_compiled_contract.md": "e2b90c5b4b5fceba187038d86277b3023731c218b28de00ddaea0d0250b50318",
}

FROZEN_BASELINE_HASHES = {
    "docs/baselines/phase_minus_one_0.6.0.json": "f34d21a32b033a524240b65002af180aa26e071fbf44385ad8679645d7b58e73",
    "docs/baselines/PHASE_MINUS_ONE_SCALE_BASELINE.md": "3c6f1de4efe2a47a6288c72e4e2dddc6f0ffb9d4f86ff431e99eeb32e2389ad2",
    "benchmarks/phase_minus_one_baseline.py": "13e7d112b0ebfe339195530311dd4b7ac0e37f60054113753b5e85772aa32ab1",
}

PAPER_MARKDOWN_FILES = {
    "README.md",
    "docs/DOCUMENTATION_INDEX.md",
    "docs/DESIGN_memory_source_compiled_view.md",
    "docs/PAPER_LICENSE.md",
    "docs/PAPER_publication_readiness_audit.md",
    "docs/PAPER_related_work_claim_ledger.md",
    "docs/PAPER_reproducibility_and_release_metadata.md",
    "docs/PAPER_review_gated_authority_source_compiled_contract.md",
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
        set(P5_FROZEN_BLOB_HASHES)
        | set(FROZEN_BASELINE_HASHES)
        | PAPER_MARKDOWN_FILES
        | {"LICENSE", "pyproject.toml"}
    )
    for relative in sorted(required_paths):
        if not (repo_root / relative).is_file():
            failures.append(f"missing paper/release file: {relative}")

    if failures:
        raise AssertionError("paper checks failed:\n- " + "\n- ".join(failures))

    for relative, expected in P5_FROZEN_BLOB_HASHES.items():
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
    if manuscript_words != 5052:
        failures.append(f"manuscript whitespace words={manuscript_words} expected=5052")

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
    if 'exclude = ["/docs/PAPER_final_integration_audit.md"]' not in pyproject:
        failures.append("pyproject.toml does not exclude the self-referential P6 receipt")

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
