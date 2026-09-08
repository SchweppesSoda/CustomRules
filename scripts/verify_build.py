#!/usr/bin/env python3
"""Verify a complete auto-build tree, including loading every MRS with Mihomo."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from build_rules import (SOURCES, adblock_lite_protections, load_toml, stable_unique,
                         parse_classical_yaml, parse_list_rules,
                         parse_cidr_list, select_ip_union,
                         parse_wildcard_domain_list, select_adblock_lite)


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
        if any(not line.endswith(",no-resolve") for line in rules):
            raise RuntimeError(f"IP LIST rule is missing no-resolve: {path.name}")
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
            yaml_rules = [rule.classical for rule in parse_classical_yaml(yaml_path)]
        if yaml_rules != list_rules(list_path, behavior):
            raise RuntimeError(f"YAML/LIST {behavior} rule mismatch: {name}")
        if len(yaml_rules) != info['rule_count']:
            raise RuntimeError(f"Manifest count mismatch: {name}")
        if hashlib.sha256('\n'.join(yaml_rules).encode()).hexdigest() != info['rules_sha256']:
            raise RuntimeError(f"Manifest rule hash mismatch: {name}")

    verify_policy_aggregates(root, manifest)
    verify_ip_selections(root, manifest)

    lite = parse_list_rules(root / 'Surge' / 'AdBlockLite.list')
    policy = load_toml(SOURCES / 'policies' / 'adblock-lite.toml')
    protected = adblock_lite_protections(policy, parse_list_rules(root / 'Surge' / 'HTTPDNS.list'))
    upstream = parse_wildcard_domain_list(
        (root / 'reports' / 'AdBlockLite-Upstream.txt').read_text(encoding='utf-8'), 'HaGeZi Light')
    expected, excluded = select_adblock_lite(upstream, protected)
    if lite != expected:
        raise RuntimeError('AdBlockLite differs from HaGeZi Light with compatibility exclusions')
    report = data_lines(root / 'reports' / 'AdBlockLite-Excluded.txt')
    if report != excluded:
        raise RuntimeError('AdBlockLite exclusion report mismatch')

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
        "AdBlockLite",
        "AdBlock",
        "HTTPDNS",
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


def verify_policy_aggregates(root: Path, manifest: dict[str, object]) -> None:
    contract = load_toml(SOURCES / 'policy-aggregates.toml')['aggregates']
    actual = {name for name, info in manifest['sets'].items() if 'aggregation' in info}
    if actual != set(contract):
        raise RuntimeError('Policy aggregate inventory differs from source contract')
    for name, spec in contract.items():
        info = manifest['sets'][name]
        if info['aggregation'] != {'policy': spec['policy'], 'members': spec['members']}:
            raise RuntimeError(f'Policy aggregate membership mismatch: {name}')
        expected = stable_unique([
            rule for member in spec['members']
            for rule in parse_list_rules(root / 'Surge' / f'{member}.list',
                                         manifest['sets'][member]['behavior'])
        ])
        found = parse_list_rules(root / 'Surge' / f'{name}.list', info['behavior'])
        if found != expected:
            raise RuntimeError(f'Policy aggregate is not the literal member union: {name}')


def verify_ip_selections(root: Path, manifest: dict[str, object]) -> None:
    contracts = {name: config for name, config in load_toml(SOURCES / 'upstreams.toml')['sets'].items()
                 if config['parser'] == 'cidr-union-excluding'}
    actual = {name for name, info in manifest['sets'].items() if 'ip_selection' in info}
    if actual != set(contracts):
        raise RuntimeError('IP selection inventory differs from source contract')
    sources = {item['url']: item['sha256'] for item in
               json.loads((root / 'SOURCES.json').read_text(encoding='utf-8'))['sources']}
    for name, config in contracts.items():
        report = f'reports/{name}-selection.json'
        if manifest['sets'][name]['ip_selection'] != report:
            raise RuntimeError(f'IP selection report path mismatch: {name}')
        evidence = json.loads((root / report).read_text(encoding='utf-8'))
        if evidence['schema'] != 1 or evidence['snapshot_api_url'] != config['snapshot_api_url']:
            raise RuntimeError(f'IP selection snapshot contract mismatch: {name}')
        sha = evidence['snapshot_commit']
        if not re.fullmatch(r'[0-9a-f]{40}', sha):
            raise RuntimeError(f'Invalid IP selection snapshot: {name}')
        response = evidence['snapshot_response']
        if (json.loads(response).get('sha') != sha or
            sources.get(config['snapshot_api_url']) != hashlib.sha256(response.encode('utf-8')).hexdigest()):
            raise RuntimeError(f'IP selection commit evidence mismatch: {name}')
        repo, ref = config['snapshot_api_url'].split('/repos/', 1)[1].split('/commits/')
        prefix = f'https://raw.githubusercontent.com/{repo}/{ref}/'
        expected_sources = [(role, url) for role, key in
                            (('primary', 'urls'), ('excluded', 'exclude_urls'), ('supplement', 'supplement_urls'))
                            for url in config[key]]
        if [(s['role'], s['source_url']) for s in evidence['sources']] != expected_sources:
            raise RuntimeError(f'IP selection sources mismatch: {name}')
        groups = {role: [] for role in ('primary', 'excluded', 'supplement')}
        for item in evidence['sources']:
            expected_url = (item['source_url'].replace(prefix, f'https://raw.githubusercontent.com/{repo}/{sha}/', 1)
                            if item['role'] != 'supplement' else item['source_url'])
            digest = hashlib.sha256(item['text'].encode('utf-8')).hexdigest()
            if item['url'] != expected_url or item['sha256'] != digest or sources.get(expected_url) != digest:
                raise RuntimeError(f'IP selection source checksum mismatch: {name}')
            groups[item['role']].extend(parse_cidr_list(item['text'].lstrip('\ufeff'), expected_url))
        expected = select_ip_union(**groups)
        found = parse_list_rules(root / 'Surge' / f'{name}.list', 'ipcidr')
        if found != expected:
            raise RuntimeError(f'IP selection differs from (primary minus CN) union supplement: {name}')


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
