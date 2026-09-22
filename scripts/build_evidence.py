#!/usr/bin/env python3
"""Bounded public build evidence. No network, compiler execution or publishing."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import tempfile
import tomllib
from urllib.parse import urlsplit

MAX_FILE = 64 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
MAX_FILES = 4096
MAX_COMPILER = 256 * 1024 * 1024
HASH = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
PUBLIC_RAW_REPOS = {
    "666OS/rules", "ACL4SSR/ACL4SSR", "MetaCubeX/meta-rules-dat",
    "blackmatrix7/ios_rule_script", "dler-io/Rules",
    "hagezi/dns-blocklists", "v2fly/domain-list-community",
}
METADATA_FILES = {"manifest.json", "SOURCES.json", "SHA256SUMS"}


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()


def compiler_identity(path: Path) -> tuple[str, int]:
    if not path.is_file() or path.is_symlink():
        raise ValueError("compiler must be a regular file")
    checksum = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_COMPILER:
                raise ValueError("compiler exceeds independent hashing limit")
            checksum.update(chunk)
    if not size:
        raise ValueError("compiler is empty")
    return checksum.hexdigest(), size


def public_url(url: str) -> bool:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.username or parsed.password or
            parsed.query or parsed.fragment or parsed.port or any(ord(c) < 33 for c in url)):
        return False
    parts = parsed.path.strip("/").split("/")
    if ".." in parts or "%" in parsed.netloc:
        return False
    if parsed.hostname == "raw.githubusercontent.com":
        return len(parts) >= 4 and "/".join(parts[:2]) in PUBLIC_RAW_REPOS
    if parsed.hostname == "api.github.com":
        return bool(re.fullmatch(r"/repos/MetaCubeX/meta-rules-dat/commits/[A-Za-z0-9._-]+", parsed.path))
    if parsed.hostname == "testingcf.jsdelivr.net":
        return parsed.path == "/gh/VirgilClyne/GetSomeFries@main/ruleset/ASN.China.list"
    return False


def safe_path(name: str) -> bool:
    path = PurePosixPath(name)
    return (bool(name) and not path.is_absolute() and str(path) == name and
            all(part not in {".", ".."} for part in path.parts) and
            not any(char in name for char in ("\\", ":", "\x00", "\n", "\r")))


def allowed_file(name: str) -> bool:
    if not safe_path(name):
        return False
    if name in {"source-snapshot/SOURCES.json", "counts.json"}:
        return True
    if name.startswith("source-snapshot/"):
        return bool(HASH.fullmatch(name.removeprefix("source-snapshot/")))
    if name.startswith(("baseline/", "candidate/")):
        prefix, relative = name.split("/", 1)
        return relative in METADATA_FILES or (prefix == "baseline" and relative.startswith("Surge/") and relative.endswith(".list"))
    if name.startswith("source/scripts/"):
        return name.removeprefix("source/scripts/") in {"build_rules.py", "verify_build.py", "build_evidence.py"}
    if name.startswith("source/sources/"):
        return PurePosixPath(name).suffix in {".toml", ".yaml", ".json", ".txt"}
    return False


def read_regular(root: Path, relative: str) -> bytes:
    if not safe_path(relative):
        raise ValueError("unsafe evidence path")
    path = root / relative
    if any(part.is_symlink() for part in (path, *path.parents) if part != root.parent):
        raise ValueError("symlinks are not evidence inputs")
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("missing evidence input")
    if path.stat().st_size > MAX_FILE:
        raise ValueError("evidence input exceeds file limit")
    body = path.read_bytes()
    if len(body) > MAX_FILE:
        raise ValueError("evidence input exceeds file limit")
    return body


def validate_sources(document: object) -> list[dict[str, str]]:
    if not isinstance(document, dict) or set(document) != {"sources"} or not isinstance(document["sources"], list):
        raise ValueError("invalid source journal")
    entries = document["sources"]
    if len(entries) > MAX_FILES:
        raise ValueError("too many source inputs")
    seen: set[str] = set()
    for item in entries:
        if not isinstance(item, dict) or set(item) != {"url", "sha256", "size"}:
            raise ValueError("invalid source journal entry")
        url, checksum, size = item["url"], item["sha256"], item["size"]
        if (not isinstance(url, str) or not public_url(url) or url in seen or
                not isinstance(checksum, str) or not HASH.fullmatch(checksum) or
                not isinstance(size, str) or not size.isdecimal() or not 0 < int(size) <= MAX_FILE):
            raise ValueError("source journal is not approved public input metadata")
        seen.add(url)
    return entries


def counts(root: Path) -> dict[str, int]:
    result = {}
    for path in sorted((root / "Surge").rglob("*.list")):
        body = read_regular(root, path.relative_to(root).as_posix())
        result[path.relative_to(root).as_posix()] = len({line.strip() for line in body.decode("utf-8-sig").splitlines() if line.strip() and not line.lstrip().startswith("#")})
    return result


def validate_baseline(root: Path, actual_counts: dict[str, int]) -> None:
    manifest = json.loads(read_regular(root, "manifest.json"))
    sets = manifest.get("sets")
    if not isinstance(sets, dict) or not sets:
        raise ValueError("baseline has no declared rule sets")
    expected = {"Surge/" + name + ".list": value["rule_count"] for name, value in sets.items()}
    if expected != actual_counts:
        raise ValueError("baseline list inventory/counts do not match published manifest")


def write_new_directory(destination: Path, files: dict[str, bytes]) -> None:
    if destination.exists():
        raise ValueError("evidence destination must not exist")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".evidence-", dir=destination.parent))
    try:
        for name, body in files.items():
            target = temporary / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        os.rename(temporary, destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def capture(*, source: Path, cache: Path, baseline: Path, candidate: Path,
            compiler: Path, source_commit: str, baseline_commit: str,
            outcome: str, destination: Path, allow_large_change: bool = False) -> dict:
    if not COMMIT.fullmatch(source_commit) or not COMMIT.fullmatch(baseline_commit):
        raise ValueError("source and baseline require full commit identities")
    if outcome not in {"success", "failure", "cancelled"}:
        raise ValueError("invalid build outcome")
    files: dict[str, bytes] = {}
    total = 0
    def add(name: str, body: bytes):
        nonlocal total
        if not allowed_file(name) or name in files or len(body) > MAX_FILE:
            raise ValueError("invalid evidence member")
        total += len(body)
        if total > MAX_TOTAL or len(files) >= MAX_FILES:
            raise ValueError("evidence bundle exceeds limits")
        files[name] = body
    journal = read_regular(cache, "SOURCES.json") if (cache / "SOURCES.json").exists() else json_bytes({"sources": []})
    entries = validate_sources(json.loads(journal))
    add("source-snapshot/SOURCES.json", journal)
    for item in entries:
        key = digest(item["url"].encode())
        body = read_regular(cache, key)
        if digest(body) != item["sha256"] or len(body) != int(item["size"]):
            raise ValueError("cached source does not match journal")
        add("source-snapshot/" + key, body)
    for name in ("build_rules.py", "verify_build.py", "build_evidence.py"):
        add("source/scripts/" + name, read_regular(source, "scripts/" + name))
    for path in sorted((source / "sources").rglob("*")):
        relative = path.relative_to(source).as_posix()
        if path.is_file() and allowed_file("source/" + relative):
            add("source/" + relative, read_regular(source, relative))
    for prefix, root in (("baseline", baseline), ("candidate", candidate)):
        for name in sorted(METADATA_FILES):
            if (root / name).exists():
                body = read_regular(root, name)
                if name == "SOURCES.json":
                    validate_sources(json.loads(body))
                add(prefix + "/" + name, body)
    for path in sorted((baseline / "Surge").rglob("*.list")):
        relative = path.relative_to(baseline).as_posix()
        add("baseline/" + relative, read_regular(baseline, relative))
    baseline_counts = counts(baseline)
    if not baseline_counts or "baseline/SOURCES.json" not in files or "baseline/manifest.json" not in files:
        raise ValueError("complete published baseline is required")
    validate_baseline(baseline, baseline_counts)
    add("counts.json", json_bytes({"baseline": baseline_counts, "candidate": counts(candidate)}))
    toolchain = tomllib.loads(files["source/sources/toolchain.toml"].decode())["mihomo"]
    compiler_sha, compiler_size = compiler_identity(compiler)
    metadata = {
        "schema": 1, "source_commit": source_commit, "baseline_commit": baseline_commit,
        "outcome": outcome, "allow_large_change": allow_large_change,
        "python_version": platform.python_version(),
        "compiler": {"version": toolchain["version"], "binary_sha256": compiler_sha, "binary_size": compiler_size,
                     "archive_sha256": toolchain["linux_amd64"]["sha256"], "platform": "linux_amd64"},
        "source_response_count": len(entries),
        "files": {name: {"sha256": digest(body), "size": len(body)} for name, body in sorted(files.items())},
    }
    write_new_directory(destination, {**files, "evidence.json": json_bytes(metadata)})
    return metadata


def verify(archive: Path, compiler: Path | None = None) -> dict:
    metadata = json.loads(read_regular(archive, "evidence.json"))
    if (metadata.get("schema") != 1 or not COMMIT.fullmatch(metadata.get("source_commit", "")) or
            not COMMIT.fullmatch(metadata.get("baseline_commit", "")) or not isinstance(metadata.get("files"), dict)):
        raise ValueError("invalid evidence manifest")
    members = metadata["files"]
    required = {"source-snapshot/SOURCES.json", "source/scripts/build_rules.py", "source/scripts/verify_build.py", "source/scripts/build_evidence.py", "source/sources/toolchain.toml", "baseline/SOURCES.json", "baseline/manifest.json", "counts.json"}
    if not required <= set(members) or len(members) > MAX_FILES:
        raise ValueError("incomplete evidence manifest")
    actual = {path.relative_to(archive).as_posix() for path in archive.rglob("*") if path.is_file()}
    if actual != set(members) | {"evidence.json"}:
        raise ValueError("unexpected or missing evidence files")
    total = 0
    for name, record in members.items():
        if not allowed_file(name) or not isinstance(record, dict) or set(record) != {"sha256", "size"}:
            raise ValueError("invalid evidence member")
        body = read_regular(archive, name)
        total += len(body)
        if total > MAX_TOTAL or digest(body) != record["sha256"] or len(body) != record["size"]:
            raise ValueError("corrupt or oversized evidence member")
    entries = validate_sources(json.loads(read_regular(archive, "source-snapshot/SOURCES.json")))
    expected_cache = {"source-snapshot/" + digest(item["url"].encode()) for item in entries}
    actual_cache = {name for name in members if name.startswith("source-snapshot/")} - {"source-snapshot/SOURCES.json"}
    if expected_cache != actual_cache:
        raise ValueError("source snapshot inventory mismatch")
    for item in entries:
        record = members["source-snapshot/" + digest(item["url"].encode())]
        if record != {"sha256": item["sha256"], "size": int(item["size"])}:
            raise ValueError("source snapshot journal mismatch")
    validate_sources(json.loads(read_regular(archive, "baseline/SOURCES.json")))
    if "candidate/SOURCES.json" in members:
        validate_sources(json.loads(read_regular(archive, "candidate/SOURCES.json")))
    baseline_counts = counts(archive / "baseline")
    validate_baseline(archive / "baseline", baseline_counts)
    recorded_counts = json.loads(read_regular(archive, "counts.json"))
    if recorded_counts.get("baseline") != baseline_counts:
        raise ValueError("baseline count summary mismatch")
    if metadata.get("source_response_count") != len(entries):
        raise ValueError("source response count mismatch")
    toolchain = tomllib.loads(read_regular(archive, "source/sources/toolchain.toml").decode())["mihomo"]
    if (metadata["compiler"]["version"] != toolchain["version"] or
            metadata["compiler"]["archive_sha256"] != toolchain["linux_amd64"]["sha256"] or
            not HASH.fullmatch(metadata["compiler"]["binary_sha256"]) or
            not 0 < metadata["compiler"]["binary_size"] <= MAX_COMPILER):
        raise ValueError("compiler metadata does not match source lock")
    if compiler is not None and compiler_identity(compiler) != (metadata["compiler"]["binary_sha256"], metadata["compiler"]["binary_size"]):
        raise ValueError("replay compiler does not match recorded binary")
    return metadata


def restore(archive: Path, destination: Path, compiler: Path) -> dict:
    metadata = verify(archive, compiler)
    if not metadata["source_response_count"]:
        raise ValueError("no successful source responses; no offline build can be replayed")
    files = {name: read_regular(archive, name) for name in metadata["files"]}
    # Source files are material only; this command never executes archived code.
    write_new_directory(destination, files)
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    capture_parser = actions.add_parser("capture")
    for name in ("source", "cache", "baseline", "candidate", "compiler", "destination"):
        capture_parser.add_argument("--" + name, type=Path, required=True)
    for name in ("source-commit", "baseline-commit", "outcome"):
        capture_parser.add_argument("--" + name, required=True)
    capture_parser.add_argument("--allow-large-change", action="store_true")
    verify_parser = actions.add_parser("verify")
    verify_parser.add_argument("archive", type=Path)
    verify_parser.add_argument("--compiler", type=Path)
    restore_parser = actions.add_parser("restore")
    restore_parser.add_argument("archive", type=Path)
    restore_parser.add_argument("destination", type=Path)
    restore_parser.add_argument("--compiler", type=Path, required=True)
    args = vars(parser.parse_args())
    action = args.pop("action")
    metadata = {"capture": capture, "verify": verify, "restore": restore}[action](**args)
    print(f"Evidence verified: outcome={metadata['outcome']} source_responses={metadata['source_response_count']}")


if __name__ == "__main__":
    main()
