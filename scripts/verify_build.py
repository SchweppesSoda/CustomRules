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


def yaml_ip_rules(path: Path) -> list[str]:
    rules: list[str] = []
    for line in data_lines(path):
        if not line.startswith("- "):
            continue
        token = line[2:].strip()
        kind = "IP-CIDR6" if ":" in token else "IP-CIDR"
        rules.append(f"{kind},{token}")
    return rules


def list_rules(path: Path, behavior: str = "classical") -> list[str]:
    rules = data_lines(path)
    if behavior == "ipcidr":
        return [
            line.removesuffix(",no-resolve")
            for line in rules
        ]
    return rules


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


def verify_behavior_sets(root: Path, manifest: dict[str, object]) -> None:
    for name, info in manifest["sets"].items():
        behavior = info.get("behavior", "classical")
        yaml_path = root / "Mihomo" / f"{name}.yaml"
        list_path = root / "Surge" / f"{name}.list"
        if behavior == "domain":
            yaml_rules = yaml_domain_rules(yaml_path)
        elif behavior == "ipcidr":
            yaml_rules = yaml_ip_rules(yaml_path)
        else:
            continue
        if yaml_rules != list_rules(list_path, behavior):
            raise RuntimeError(f"YAML/LIST {behavior} rule mismatch: {name}")

    aggregate = set(list_rules(root / "Surge" / "Banking.list", "domain"))
    region_sets = {
        region: set(
            list_rules(root / "Surge" / "Banking" / f"{region}.list", "domain")
        )
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


def verify_manifest(root: Path) -> dict[str, object]:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != 2:
        raise RuntimeError("manifest schema must be 2")
    if manifest.get("branch") != "auto-build":
        raise RuntimeError("manifest branch must be auto-build")
    required = {
        "Crypto",
        "Banking",
        "Emby",
        "AICN",
        "MicrosoftCN",
        "ScholarCN",
        "ScholarGlobal",
        "SteamCN",
        "GameDownloadCN",
        "GameDownload",
        "GoogleGlobal",
        "ApplePush",
        "Telegram",
        "Twitter",
        "GoogleFCM",
        "YouTube",
        "Netflix",
        "ProxyGlobal",
        "IP/ApplePush",
        "IP/Telegram",
        "IP/Twitter",
        "IP/GoogleFCM",
        "IP/YouTube",
        "IP/Netflix",
        "IP/Google",
        "IP/Proxy",
        *(f"Banking/{region}" for region in REGIONS),
    }
    missing = required - set(manifest["sets"])
    if missing:
        raise RuntimeError(f"Missing manifest rule sets: {sorted(missing)}")
    for name, info in manifest["sets"].items():
        if info.get("behavior") not in {"classical", "domain", "ipcidr"}:
            raise RuntimeError(f"Invalid manifest behavior for {name}")
        if "mrs" in info.get("formats", []) and info.get("mrs_behavior") not in {
            "domain",
            "ipcidr",
        }:
            raise RuntimeError(f"Missing MRS behavior for {name}")
    return manifest


def verify_mrs_loading(root: Path, mihomo: Path, manifest: dict[str, object]) -> None:
    mrs_files = sorted((root / "Mihomo").rglob("*.mrs"))
    if not mrs_files:
        raise RuntimeError("No MRS files were generated")
    with tempfile.TemporaryDirectory(prefix="customrules-config-") as temporary:
        home = Path(temporary)
        providers: list[str] = []
        rules: list[str] = []
        for index, path in enumerate(mrs_files):
            name = f"set_{index}"
            set_name = path.relative_to(root / "Mihomo").with_suffix("").as_posix()
            behavior = manifest["sets"].get(set_name, {}).get("mrs_behavior")
            if behavior not in {"domain", "ipcidr"}:
                raise RuntimeError(f"MRS file is not registered with behavior: {set_name}")
            copied = home / f"{name}.mrs"
            shutil.copy2(path, copied)
            providers.extend(
                [
                    f"  {name}:",
                    "    type: file",
                    f"    behavior: {behavior}",
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
    manifest = verify_manifest(args.output)
    verify_behavior_sets(args.output, manifest)
    verify_checksums(args.output)
    verify_mrs_loading(args.output, args.mihomo, manifest)
    print(f"Verified generated tree: {args.output}")


if __name__ == "__main__":
    main()
