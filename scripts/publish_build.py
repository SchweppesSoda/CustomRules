#!/usr/bin/env python3
"""Overlay a verified build onto auto-build without deleting unregistered outputs."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


METADATA = {"manifest.json", "SOURCES.json", "SHA256SUMS"}


def artifact_paths(manifest_path: Path) -> set[Path]:
    if not manifest_path.exists():
        return set()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    paths: set[Path] = set()
    for name, info in manifest.get("sets", {}).items():
        formats = set(info.get("formats", []))
        if "yaml" in formats:
            paths.add(Path("Mihomo") / f"{name}.yaml")
        if "mrs" in formats:
            paths.add(Path("Mihomo") / f"{name}.mrs")
        if "list" in formats:
            paths.add(Path("Surge") / f"{name}.list")
    return paths


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--publish", type=Path, required=True)
    args = parser.parse_args()

    old_owned = artifact_paths(args.publish / "manifest.json")
    new_owned = artifact_paths(args.build / "manifest.json")
    for relative in sorted(old_owned - new_owned):
        target = args.publish / relative
        if target.is_file():
            target.unlink()

    for source in sorted(path for path in args.build.rglob("*") if path.is_file()):
        relative = source.relative_to(args.build)
        target = args.publish / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    for name in METADATA:
        if not (args.publish / name).is_file():
            raise RuntimeError(f"Published metadata is missing: {name}")
    print(f"Published {len(new_owned)} registered artifacts into {args.publish}")


if __name__ == "__main__":
    main()
