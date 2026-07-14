"""Deterministic source and artifact checks for a memdsl release candidate."""

from __future__ import annotations

import argparse
import ast
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
