#!/usr/bin/env python3
"""Verify a complete auto-build tree, including loading every MRS with Mihomo."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


REGIONS = (
    "Global",
    "NorthAmerica",
    "Europe",
    "HongKongMacau",
    "Singapore",
    "JapanKorea",
    "MiddleEast",
    "Other",
)


def data_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#") and line.strip() != "payload:"
    ]


def yaml_domain_rules(path: Path) -> list[str]:
    rules: list[str] = []
    for line in data_lines(path):
        if not line.startswith("- "):
            continue
        token = line[2:].strip()
        if token.startswith("+."):
            rules.append(f"DOMAIN-SUFFIX,{token[2:]}")
        else:
            rules.append(f"DOMAIN,{token}")
    return rules


def list_rules(path: Path) -> list[str]:
    return data_lines(path)


def verify_checksums(root: Path) -> None:
    expected: dict[str, str] = {}
    for line in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        expected[relative] = digest
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if (
            path.is_file()
            and path.name != "SHA256SUMS"
            and ".git" not in path.relative_to(root).parts
        )
    }
    if set(expected) != actual_files:
        raise RuntimeError("SHA256SUMS inventory does not match generated files")
    for relative, digest in expected.items():
        body = (root / relative).read_bytes()
        actual = hashlib.sha256(body).hexdigest()
        if actual != digest and b"\r\n" in body:
            actual = hashlib.sha256(body.replace(b"\r\n", b"\n")).hexdigest()
        if actual != digest:
            raise RuntimeError(f"Checksum mismatch: {relative}")


def verify_domain_sets(root: Path) -> None:
    names = ["Crypto", "Banking", *(f"Banking/{region}" for region in REGIONS)]
    for name in names:
        yaml_path = root / "Mihomo" / f"{name}.yaml"
        list_path = root / "Surge" / f"{name}.list"
        if yaml_domain_rules(yaml_path) != list_rules(list_path):
            raise RuntimeError(f"YAML/LIST rule mismatch: {name}")

    aggregate = set(list_rules(root / "Surge" / "Banking.list"))
    region_sets = {
        region: set(list_rules(root / "Surge" / "Banking" / f"{region}.list"))
        for region in REGIONS
    }
    union = set().union(*region_sets.values())
    if aggregate != union:
        raise RuntimeError("Banking aggregate is not equal to the region union")
    for index, left in enumerate(REGIONS):
        for right in REGIONS[index + 1:]:
            overlap = region_sets[left] & region_sets[right]
            if overlap:
                raise RuntimeError(f"Banking region overlap: {left}/{right}: {sorted(overlap)}")


def verify_manifest(root: Path) -> None:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("branch") != "auto-build":
        raise RuntimeError("manifest branch must be auto-build")
    required = {
        "Crypto",
        "Banking",
        *(f"Banking/{region}" for region in REGIONS),
    }
    missing = required - set(manifest["sets"])
    if missing:
        raise RuntimeError(f"Missing manifest rule sets: {sorted(missing)}")


def verify_mrs_loading(root: Path, mihomo: Path) -> None:
    mrs_files = sorted((root / "Mihomo").rglob("*.mrs"))
    if not mrs_files:
        raise RuntimeError("No MRS files were generated")
    with tempfile.TemporaryDirectory(prefix="customrules-config-") as temporary:
        home = Path(temporary)
        providers: list[str] = []
        rules: list[str] = []
        for index, path in enumerate(mrs_files):
            name = f"set_{index}"
            copied = home / f"{name}.mrs"
            shutil.copy2(path, copied)
            providers.extend(
                [
                    f"  {name}:",
                    "    type: file",
                    "    behavior: domain",
                    "    format: mrs",
                    f"    path: {json.dumps(copied.as_posix())}",
                ]
            )
            rules.append(f"  - RULE-SET,{name},DIRECT")
        config = "\n".join(
            [
                "mixed-port: 7890",
                "mode: rule",
                "log-level: silent",
                "proxies: []",
                "proxy-groups: []",
                "rule-providers:",
                *providers,
                "rules:",
                *rules,
                "  - MATCH,DIRECT",
                "",
            ]
        )
        config_path = home / "config.yaml"
        config_path.write_text(config, encoding="utf-8", newline="\n")
        result = subprocess.run(
            [str(mihomo), "-d", temporary, "-t", "-f", str(config_path)],
            text=True,
            capture_output=True,
            check=False,
        )
    if result.returncode != 0:
        raise RuntimeError(f"Mihomo failed to load generated MRS files:\n{result.stdout}{result.stderr}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mihomo", type=Path, required=True)
    args = parser.parse_args()
    verify_manifest(args.output)
    verify_domain_sets(args.output)
    verify_checksums(args.output)
    verify_mrs_loading(args.output, args.mihomo)
    print(f"Verified generated tree: {args.output}")


if __name__ == "__main__":
    main()
