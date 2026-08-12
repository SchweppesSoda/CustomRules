#!/usr/bin/env python3
"""Build deterministic CustomRules artifacts from reviewed sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
import urllib.request
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "sources"
RULE_RE = re.compile(r"^(DOMAIN|DOMAIN-SUFFIX|DOMAIN-KEYWORD|IP-CIDR6?|PROCESS-NAME),(.+)$")
DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)[a-z0-9](?:[a-z0-9_-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9_-]{0,61}[a-z0-9])?)*$"
)
DOMAIN_TYPES = {"DOMAIN", "DOMAIN-SUFFIX"}
SHARED_INFRASTRUCTURE = (
    "amazonaws.com",
    "akamaized.net",
    "appsflyersdk.com",
    "azureedge.net",
    "cloudfront.net",
    "cloudinary.com",
    "freshchat.com",
    "googleapis.com",
    "gstatic.com",
    "zendesk.com",
)
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
REQUIRED_CRYPTO_IDS = {
    "binance", "okx", "bybit", "bitget", "mexc", "gate", "kucoin",
    "coinbase", "kraken", "crypto-com", "gemini", "htx", "bingx", "coinw",
    "whitebit", "bitfinex", "bitstamp", "bitmex", "deribit", "bitflyer",
    "coincheck", "upbit", "bithumb", "pionex", "metamask", "trust-wallet",
    "onekey", "safepal", "ledger", "trezor", "tangem", "rabby", "imtoken",
    "phantom", "exodus", "redotpay", "fiat24", "straitsx",
}
REQUIRED_BANKING_IDS = {
    "wise", "ifast-global-bank", "starryblu", "n26", "revolut",
    "airwallex", "worldfirst", "payoneer", "currenxie", "statrys", "aspire",
    "mercury", "brex",
}
CRYPTO_OUT_OF_SCOPE = {
    "1inch.io", "aave.com", "bitcoin.org", "bitcoincore.org", "coindesk.com",
    "coingecko.com", "coinmarketcap.com", "cryptocompare.com", "curve.fi",
    "ethereum.org", "opensea.io", "solana.com", "uniswap.org",
}
STOPPED_CRYPTO_SERVICES = {"bittrex.com", "ftx.com", "localbitcoins.com"}
BANKING_OUT_OF_SCOPE = {
    "binance.com", "bitcoin.org", "mastercard.com", "paypal.com", "stripe.com",
    "visa.com",
}


@dataclass(frozen=True, order=True)
class Rule:
    kind: str
    value: str

    @property
    def classical(self) -> str:
        return f"{self.kind},{self.value}"

    @property
    def domain_token(self) -> str:
        if self.kind == "DOMAIN":
            return self.value
        if self.kind == "DOMAIN-SUFFIX":
            return f"+.{self.value}"
        raise ValueError(f"Not a domain rule: {self.classical}")


class SourceRegistry:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, str]] = {}

    def add(self, url: str, body: bytes) -> None:
        self.items[url] = {
            "sha256": hashlib.sha256(body).hexdigest(),
            "size": str(len(body)),
        }

    def as_json(self) -> dict[str, object]:
        return {
            "sources": [
                {"url": url, **self.items[url]}
                for url in sorted(self.items)
            ]
        }


class Fetcher:
    def __init__(self, registry: SourceRegistry) -> None:
        self.registry = registry
        self.cache: dict[str, bytes] = {}

    def bytes(self, url: str) -> bytes:
        if url not in self.cache:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "CustomRules-AutoBuild/1.0"},
            )
            with urllib.request.urlopen(request, timeout=45) as response:
                body = response.read()
            if not body.strip():
                raise RuntimeError(f"Upstream returned empty content: {url}")
            self.cache[url] = body
            self.registry.add(url, body)
        return self.cache[url]

    def text(self, url: str) -> str:
        return self.bytes(url).decode("utf-8-sig")


def load_toml(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def normalize_domain(raw: str) -> str:
    domain = raw.strip().rstrip(".").lower()
    try:
        domain = domain.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError(f"Invalid internationalized domain: {raw}") from exc
    if not DOMAIN_RE.fullmatch(domain):
        raise ValueError(f"Invalid domain: {raw}")
    return domain


def parse_catalog_domain(raw: str) -> Rule:
    prefix, separator, value = raw.partition(":")
    if not separator or prefix not in {"exact", "suffix"}:
        raise ValueError(f"Catalog domain must use exact: or suffix:: {raw}")
    return Rule("DOMAIN" if prefix == "exact" else "DOMAIN-SUFFIX", normalize_domain(value))


def parse_classical_yaml(path: Path) -> list[Rule]:
    rules: list[Rule] = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line.startswith("- "):
            continue
        match = RULE_RE.fullmatch(line[2:].strip())
        if not match:
            raise ValueError(f"Unsupported rule in {path}: {line}")
        kind, value = match.groups()
        if kind in DOMAIN_TYPES:
            value = normalize_domain(value)
        else:
            value = value.strip()
        rules.append(Rule(kind, value))
    if not rules:
        raise ValueError(f"No rules found in {path}")
    return stable_unique(rules)


def parse_meta_list(body: str, url: str) -> list[Rule]:
    rules: list[Rule] = []
    for raw in body.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("+."):
            rules.append(Rule("DOMAIN-SUFFIX", normalize_domain(line[2:])))
        else:
            rules.append(Rule("DOMAIN", normalize_domain(line)))
    if not rules:
        raise RuntimeError(f"No supported domains found in {url}")
    return stable_unique(rules)


def parse_v2fly_component(
    component: str,
    base_url: str,
    fetcher: Fetcher,
    stack: tuple[str, ...] = (),
) -> list[Rule]:
    if component in stack:
        raise RuntimeError(f"V2Fly include cycle: {' -> '.join((*stack, component))}")
    url = f"{base_url.rstrip('/')}/{component}"
    rules: list[Rule] = []
    for raw in fetcher.text(url).splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        token = line.split()[0]
        if token.startswith("include:"):
            rules.extend(
                parse_v2fly_component(
                    token.removeprefix("include:"),
                    base_url,
                    fetcher,
                    (*stack, component),
                )
            )
            continue
        if token.startswith(("keyword:", "regexp:")):
            raise RuntimeError(f"Unsupported broad V2Fly token in {url}: {token}")
        if token.startswith("full:"):
            rules.append(Rule("DOMAIN", normalize_domain(token.removeprefix("full:"))))
        else:
            rules.append(Rule("DOMAIN-SUFFIX", normalize_domain(token.removeprefix("domain:"))))
    if not rules:
        raise RuntimeError(f"No supported domains found in {url}")
    return stable_unique(rules)


def stable_unique(rules: list[Rule]) -> list[Rule]:
    return list(dict.fromkeys(rules))


def compact_domains(rules: list[Rule]) -> list[Rule]:
    non_domains = [rule for rule in rules if rule.kind not in DOMAIN_TYPES]
    exact = {rule.value for rule in rules if rule.kind == "DOMAIN"}
    suffixes = {rule.value for rule in rules if rule.kind == "DOMAIN-SUFFIX"}
    kept_suffixes: set[str] = set()
    for domain in sorted(suffixes, key=lambda value: (value.count("."), value)):
        if not any(domain == parent or domain.endswith(f".{parent}") for parent in kept_suffixes):
            kept_suffixes.add(domain)
    exact = {
        domain
        for domain in exact
        if not any(domain == suffix or domain.endswith(f".{suffix}") for suffix in kept_suffixes)
    }
    domain_rules = [Rule("DOMAIN", value) for value in sorted(exact)]
    domain_rules.extend(Rule("DOMAIN-SUFFIX", value) for value in sorted(kept_suffixes))
    return sorted(non_domains) + domain_rules


def is_shared_infrastructure_suffix(rule: Rule) -> bool:
    return rule.kind == "DOMAIN-SUFFIX" and any(
        rule.value == item or rule.value.endswith(f".{item}")
        for item in SHARED_INFRASTRUCTURE
    )


def validate_no_shared_suffix(name: str, rules: list[Rule]) -> None:
    for rule in rules:
        if is_shared_infrastructure_suffix(rule):
            raise ValueError(f"{name}: shared infrastructure suffix is forbidden: {rule.value}")


def render_classical_yaml(name: str, rules: list[Rule]) -> str:
    lines = [
        "# AUTO-GENERATED. DO NOT EDIT.",
        f"# Rule set: {name}",
        "payload:",
    ]
    lines.extend(f"  - {rule.classical}" for rule in rules)
    return "\n".join(lines) + "\n"


def render_domain_yaml(name: str, rules: list[Rule]) -> str:
    if any(rule.kind not in DOMAIN_TYPES for rule in rules):
        raise ValueError(f"{name}: domain YAML cannot contain non-domain rules")
    lines = [
        "# AUTO-GENERATED. DO NOT EDIT.",
        f"# Rule set: {name}",
        "payload:",
    ]
    lines.extend(f"  - {rule.domain_token}" for rule in rules)
    return "\n".join(lines) + "\n"


def render_list(name: str, rules: list[Rule]) -> str:
    lines = [
        "# AUTO-GENERATED. DO NOT EDIT.",
        f"# Rule set: {name}",
    ]
    lines.extend(rule.classical for rule in rules)
    return "\n".join(lines) + "\n"


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_catalog(
    path: Path,
    base_url: str,
    fetcher: Fetcher,
    allowed_kinds: set[str],
    allowed_regions: set[str] | None = None,
    required_entity_ids: set[str] | None = None,
) -> tuple[list[Rule], dict[str, list[Rule]], list[dict[str, object]]]:
    document = load_toml(path)
    entities = document.get("entities", [])
    if not isinstance(entities, list) or not entities:
        raise ValueError(f"No entities in {path}")
    all_rules: list[Rule] = []
    regional: dict[str, list[Rule]] = {region: [] for region in REGIONS} if allowed_regions else {}
    entity_report: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    seen_banking_rules: dict[Rule, str] = {}
    for raw_entity in entities:
        entity = dict(raw_entity)
        entity_id = str(entity["id"])
        if entity_id in seen_ids:
            raise ValueError(f"Duplicate entity id in {path}: {entity_id}")
        seen_ids.add(entity_id)
        kind = str(entity["kind"])
        if kind not in allowed_kinds:
            raise ValueError(f"Unsupported entity kind for {entity_id}: {kind}")
        region = str(entity.get("region", ""))
        if allowed_regions is not None and region not in allowed_regions:
            raise ValueError(f"Unsupported region for {entity_id}: {region}")
        rules = [parse_catalog_domain(value) for value in entity.get("domains", [])]
        for component in entity.get("upstream_components", []):
            upstream_rules = parse_v2fly_component(str(component), base_url, fetcher)
            rules.extend(rule for rule in upstream_rules if not is_shared_infrastructure_suffix(rule))
        rules = compact_domains(stable_unique(rules))
        if entity.get("required", False) and not rules:
            raise ValueError(f"Required entity lost all domains: {entity_id}")
        if not rules:
            raise ValueError(f"Entity has no domains: {entity_id}")
        if allowed_regions is not None:
            for rule in rules:
                previous = seen_banking_rules.get(rule)
                if previous and previous != region:
                    raise ValueError(
                        f"Banking rule occurs in multiple regions: {rule.classical} ({previous}, {region})"
                    )
                seen_banking_rules[rule] = region
            regional[region].extend(rules)
        all_rules.extend(rules)
        entity_report.append(
            {
                "id": entity_id,
                "name": entity["name"],
                "kind": kind,
                "region": region or None,
                "required": bool(entity.get("required", False)),
                "rule_count": len(rules),
            }
        )
    if required_entity_ids:
        missing = sorted(required_entity_ids - seen_ids)
        if missing:
            raise ValueError(f"Required entities missing from {path}: {', '.join(missing)}")
    return compact_domains(stable_unique(all_rules)), {
        key: compact_domains(stable_unique(value)) for key, value in regional.items()
    }, entity_report


def parse_list_rules(path: Path) -> list[Rule]:
    rules: list[Rule] = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = RULE_RE.fullmatch(line)
        if not match:
            raise ValueError(f"Unsupported generated list rule in {path}: {line}")
        rules.append(Rule(*match.groups()))
    return rules


def validate_forbidden_domains(name: str, rules: list[Rule], forbidden: set[str]) -> None:
    for rule in rules:
        if any(
            rule.value == domain or rule.value.endswith(f".{domain}")
            for domain in forbidden
        ):
            raise ValueError(f"{name}: forbidden out-of-scope domain: {rule.value}")


def rules_overlap(left: Rule, right: Rule) -> bool:
    if left == right:
        return True
    if left.kind == "DOMAIN-SUFFIX":
        if right.value == left.value or right.value.endswith(f".{left.value}"):
            return True
    if right.kind == "DOMAIN-SUFFIX":
        if left.value == right.value or left.value.endswith(f".{right.value}"):
            return True
    return False


def validate_region_exclusivity(regions: dict[str, list[Rule]]) -> None:
    names = list(REGIONS)
    for index, left_name in enumerate(names):
        if not regions[left_name]:
            raise ValueError(f"Banking region is empty: {left_name}")
        for right_name in names[index + 1:]:
            for left in regions[left_name]:
                for right in regions[right_name]:
                    if rules_overlap(left, right):
                        raise ValueError(
                            "Banking regions overlap: "
                            f"{left_name}:{left.classical} and {right_name}:{right.classical}"
                        )


def enforce_baseline(output: Path, baseline: Path, allow_large_change: bool) -> None:
    if allow_large_change or not baseline.exists():
        return
    for current in sorted((output / "Surge").rglob("*.list")):
        relative = current.relative_to(output)
        previous = baseline / relative
        if not previous.exists():
            continue
        old = set(parse_list_rules(previous))
        new = set(parse_list_rules(current))
        if not old:
            continue
        reduction = max(0, len(old) - len(new)) / len(old)
        change = len(old.symmetric_difference(new)) / len(old)
        if reduction > 0.05:
            raise RuntimeError(f"Safety threshold: {relative} shrank by {reduction:.1%}")
        if change > 0.20:
            raise RuntimeError(f"Safety threshold: {relative} changed by {change:.1%}")


def compile_mrs(mihomo: Path, source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [str(mihomo), "convert-ruleset", "domain", "yaml", str(source), str(target)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or not target.exists() or target.stat().st_size == 0:
        raise RuntimeError(f"MRS compile failed for {source}: {result.stdout}{result.stderr}")
    with tempfile.TemporaryDirectory(prefix="customrules-mrs-") as temporary:
        roundtrip = Path(temporary) / "roundtrip.txt"
        result = subprocess.run(
            [str(mihomo), "convert-ruleset", "domain", "mrs", str(target), str(roundtrip)],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0 or not roundtrip.exists():
            raise RuntimeError(f"MRS round-trip failed for {target}: {result.stdout}{result.stderr}")
        expected = [rule.domain_token for rule in parse_domain_yaml(source)]
        actual = [line.strip() for line in roundtrip.read_text(encoding="utf-8").splitlines() if line.strip()]
        if set(expected) != set(actual):
            raise RuntimeError(f"MRS round-trip mismatch for {target}")


def parse_domain_yaml(path: Path) -> list[Rule]:
    rules: list[Rule] = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line.startswith("- "):
            continue
        token = line[2:].strip()
        if token.startswith("+."):
            rules.append(Rule("DOMAIN-SUFFIX", normalize_domain(token[2:])))
        else:
            rules.append(Rule("DOMAIN", normalize_domain(token)))
    return rules


def render_candidates(
    url: str,
    body: str,
    registered_components: set[str],
    production: set[Rule],
) -> str:
    candidates: list[str] = []
    for raw in body.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        token = line.split()[0]
        if token.startswith("include:"):
            component = token.removeprefix("include:")
            if component not in registered_components:
                candidates.append(f"UNREGISTERED-COMPONENT,{component}")
            continue
        if token.startswith(("keyword:", "regexp:")):
            candidates.append(f"UNSUPPORTED,{token}")
            continue
        rule = Rule(
            "DOMAIN" if token.startswith("full:") else "DOMAIN-SUFFIX",
            normalize_domain(token.removeprefix("full:").removeprefix("domain:")),
        )
        if rule not in production:
            candidates.append(f"UNMAPPED-DOMAIN,{rule.classical}")
    lines = [
        "# AUTO-GENERATED REVIEW REPORT. NOT USED FOR ROUTING.",
        f"# Candidate source: {url}",
        *sorted(set(candidates)),
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mihomo", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--allow-large-change", action="store_true")
    parser.add_argument("--source-commit", default=os.environ.get("GITHUB_SHA", "working-tree"))
    args = parser.parse_args()

    if not args.mihomo.is_file():
        raise FileNotFoundError(f"Mihomo executable not found: {args.mihomo}")
    if args.output.exists():
        shutil.rmtree(args.output)
    args.output.mkdir(parents=True)

    upstream_config = load_toml(SOURCES / "upstreams.toml")
    v2fly_base = str(upstream_config["v2fly"]["base_url"])
    registry = SourceRegistry()
    fetcher = Fetcher(registry)
    sets: dict[str, list[Rule]] = {}
    domain_yaml_sets: set[str] = {"Crypto", "Banking"}
    entity_reports: dict[str, list[dict[str, object]]] = {}

    for path in sorted((SOURCES / "manual").glob("*.yaml")):
        sets[path.stem] = parse_classical_yaml(path)

    for name, config in sorted(upstream_config.get("sets", {}).items()):
        rules: list[Rule] = []
        for url in config["urls"]:
            rules.extend(parse_meta_list(fetcher.text(str(url)), str(url)))
        sets[name] = compact_domains(stable_unique(rules))

    crypto, _, entity_reports["Crypto"] = build_catalog(
        SOURCES / "catalog" / "crypto.toml",
        v2fly_base,
        fetcher,
        {"exchange", "custodian", "wallet", "hardware-wallet", "onramp", "crypto-card"},
        required_entity_ids=REQUIRED_CRYPTO_IDS,
    )
    validate_no_shared_suffix("Crypto", crypto)
    validate_forbidden_domains(
        "Crypto", crypto, CRYPTO_OUT_OF_SCOPE | STOPPED_CRYPTO_SERVICES
    )
    sets["Crypto"] = crypto

    banking, regions, entity_reports["Banking"] = build_catalog(
        SOURCES / "catalog" / "banking.toml",
        v2fly_base,
        fetcher,
        {"bank", "digital-bank", "cross-border-account", "licensed-fintech"},
        set(REGIONS),
        REQUIRED_BANKING_IDS,
    )
    validate_no_shared_suffix("Banking", banking)
    validate_forbidden_domains("Banking", banking, BANKING_OUT_OF_SCOPE)
    sets["Banking"] = banking
    union = set().union(*(set(value) for value in regions.values()))
    if union != set(banking):
        raise RuntimeError("Banking region union does not equal Banking aggregate")
    validate_region_exclusivity(regions)

    manifests: dict[str, dict[str, object]] = {}
    for name, rules in sorted(sets.items()):
        rules = stable_unique(rules)
        is_domain_only = all(rule.kind in DOMAIN_TYPES for rule in rules)
        yaml_path = args.output / "Mihomo" / f"{name}.yaml"
        list_path = args.output / "Surge" / f"{name}.list"
        if name in domain_yaml_sets:
            write_text(yaml_path, render_domain_yaml(name, rules))
            yaml_rules = parse_domain_yaml(yaml_path)
        else:
            write_text(yaml_path, render_classical_yaml(name, rules))
            yaml_rules = parse_classical_yaml(yaml_path)
        write_text(list_path, render_list(name, rules))
        if yaml_rules != parse_list_rules(list_path):
            raise RuntimeError(f"YAML/LIST mismatch for {name}")
        formats = ["yaml", "list"]
        if is_domain_only:
            compile_source = yaml_path
            if name not in domain_yaml_sets:
                compile_source = args.output / ".compile" / f"{name}.yaml"
                write_text(compile_source, render_domain_yaml(name, rules))
            compile_mrs(args.mihomo, compile_source, args.output / "Mihomo" / f"{name}.mrs")
            formats.append("mrs")
        manifests[name] = {
            "rule_count": len(rules),
            "formats": formats,
            "rules_sha256": hashlib.sha256(
                "\n".join(rule.classical for rule in rules).encode()
            ).hexdigest(),
        }

    for region, rules in regions.items():
        name = f"Banking/{region}"
        yaml_path = args.output / "Mihomo" / "Banking" / f"{region}.yaml"
        list_path = args.output / "Surge" / "Banking" / f"{region}.list"
        write_text(yaml_path, render_domain_yaml(name, rules))
        write_text(list_path, render_list(name, rules))
        if parse_domain_yaml(yaml_path) != parse_list_rules(list_path):
            raise RuntimeError(f"YAML/LIST mismatch for {name}")
        compile_mrs(args.mihomo, yaml_path, args.output / "Mihomo" / "Banking" / f"{region}.mrs")
        manifests[name] = {
            "rule_count": len(rules),
            "formats": ["yaml", "list", "mrs"],
            "rules_sha256": hashlib.sha256(
                "\n".join(rule.classical for rule in rules).encode()
            ).hexdigest(),
        }

    candidate_url = str(upstream_config["crypto_candidates"]["url"])
    registered = {
        str(component)
        for entity in load_toml(SOURCES / "catalog" / "crypto.toml")["entities"]
        for component in entity.get("upstream_components", [])
    }
    write_text(
        args.output / "reports" / "Crypto-Unmapped-Candidates.txt",
        render_candidates(candidate_url, fetcher.text(candidate_url), registered, set(crypto)),
    )

    shutil.rmtree(args.output / ".compile", ignore_errors=True)
    manifest = {
        "schema": 1,
        "branch": "auto-build",
        "source_commit": args.source_commit,
        "mihomo_version": load_toml(SOURCES / "toolchain.toml")["mihomo"]["version"],
        "sets": manifests,
        "entities": entity_reports,
    }
    write_text(args.output / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    write_text(args.output / "SOURCES.json", json.dumps(registry.as_json(), indent=2, sort_keys=True) + "\n")

    if args.baseline:
        enforce_baseline(args.output, args.baseline, args.allow_large_change)

    checksum_files = [
        path for path in args.output.rglob("*") if path.is_file() and path.name != "SHA256SUMS"
    ]
    checksum_lines = [
        f"{file_sha256(path)}  {path.relative_to(args.output).as_posix()}"
        for path in sorted(checksum_files)
    ]
    write_text(args.output / "SHA256SUMS", "\n".join(checksum_lines) + "\n")
    print(f"Built {len(manifests)} rule sets in {args.output}")


if __name__ == "__main__":
    main()
