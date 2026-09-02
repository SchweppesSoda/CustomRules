#!/usr/bin/env python3
"""Build deterministic CustomRules artifacts from reviewed sources."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
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
RULE_RE = re.compile(
    r"^(DOMAIN|DOMAIN-SUFFIX|DOMAIN-KEYWORD|IP-CIDR6?|PROCESS-NAME|USER-AGENT),(.+)$"
)
DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)[a-z0-9](?:[a-z0-9_-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9_-]{0,61}[a-z0-9])?)*$"
)
DOMAIN_TYPES = {"DOMAIN", "DOMAIN-SUFFIX"}
IP_TYPES = {"IP-CIDR", "IP-CIDR6"}
AIRPORT_DOMAIN_SOURCE_NAMES = frozenset({"AirportServers", "AirportServersCTC"})
BEHAVIOR_TYPES = {
    "domain": DOMAIN_TYPES,
    "ipcidr": IP_TYPES,
}
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

    @property
    def ip_token(self) -> str:
        if self.kind in IP_TYPES:
            return self.value
        raise ValueError(f"Not an IP rule: {self.classical}")


@dataclass
class RuleSet:
    rules: list[Rule]
    behavior: str


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


def normalize_ip_network(raw: str) -> Rule:
    token = raw.strip()
    if token.startswith("IP-CIDR6:"):
        token = token.removeprefix("IP-CIDR6:")
    elif token.startswith("IP-CIDR:"):
        token = token.removeprefix("IP-CIDR:")
    try:
        network = ipaddress.ip_network(token, strict=False)
    except ValueError as exc:
        raise ValueError(f"Invalid IP network: {raw}") from exc
    kind = "IP-CIDR6" if network.version == 6 else "IP-CIDR"
    return Rule(kind, network.with_prefixlen)


def canonical_ip_networks(rules: list[Rule]) -> dict[int, tuple[str, ...]]:
    """Return the exact address space after lossless CIDR aggregation."""
    grouped: dict[int, list[ipaddress.IPv4Network | ipaddress.IPv6Network]] = {
        4: [],
        6: [],
    }
    for rule in rules:
        if rule.kind not in IP_TYPES:
            raise ValueError(f"Not an IP rule: {rule.classical}")
        network = ipaddress.ip_network(rule.value)
        grouped[network.version].append(network)
    canonical: dict[int, tuple[str, ...]] = {}
    for version in (4, 6):
        canonical[version] = tuple(
            str(network)
            for network in ipaddress.collapse_addresses(grouped[version])
        )
    return canonical


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


def validate_airport_domain_source(
    name: str, rules: list[Rule], *, stage: str = "source"
) -> None:
    """Keep the two airport DNS sources strictly domain-only.

    Other classical sources, including MyDirect, may legitimately contain
    IP-CIDR/IP-CIDR6 rules.  This check is deliberately keyed to the two
    AirportServers source names instead of changing the global parser.
    """

    if name not in AIRPORT_DOMAIN_SOURCE_NAMES:
        return
    invalid = [rule.classical for rule in rules if rule.kind not in DOMAIN_TYPES]
    if invalid:
        preview = ", ".join(invalid[:3])
        raise ValueError(
            f"{name}: {stage} must contain only DOMAIN/DOMAIN-SUFFIX rules: {preview}"
        )


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


def parse_cidr_list(body: str, url: str) -> list[Rule]:
    rules: list[Rule] = []
    for raw in body.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith(("IP-CIDR,", "IP-CIDR6,")):
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 2:
                raise ValueError(f"Malformed IP rule in {url}: {line}")
            line = parts[1]
        rules.append(normalize_ip_network(line))
    if not rules:
        raise RuntimeError(f"No supported IP networks found in {url}")
    return stable_unique(rules)


def parse_classical_list(
    body: str,
    url: str,
    behavior: str,
    keyword_suffixes: set[str],
) -> tuple[list[Rule], list[str]]:
    selected: list[Rule] = []
    unsupported: list[str] = []
    allowed = BEHAVIOR_TYPES[behavior]
    for line_number, raw in enumerate(body.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split(",")]
        kind = parts[0]
        if kind == "DOMAIN-KEYWORD" and len(parts) >= 2:
            value = parts[1]
            if value in keyword_suffixes:
                mapped = Rule("DOMAIN-SUFFIX", normalize_domain(value))
                if mapped.kind in allowed:
                    selected.append(mapped)
                continue
        if kind in DOMAIN_TYPES and len(parts) >= 2:
            if len(parts) > 2:
                unsupported.append(f"{url}:{line_number}:{line}")
                continue
            rule = Rule(kind, normalize_domain(parts[1]))
        elif kind in IP_TYPES and len(parts) >= 2:
            if any(option != "no-resolve" for option in parts[2:]):
                unsupported.append(f"{url}:{line_number}:{line}")
                continue
            rule = normalize_ip_network(parts[1])
        else:
            unsupported.append(f"{url}:{line_number}:{line}")
            continue
        if rule.kind in allowed:
            selected.append(rule)
    if not selected:
        raise RuntimeError(f"No {behavior} rules found in {url}")
    return stable_unique(selected), unsupported


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


def build_upstream_set(
    name: str,
    config: dict[str, object],
    v2fly_base: str,
    fetcher: Fetcher,
) -> tuple[RuleSet, list[str]]:
    behavior = str(config.get("behavior", ""))
    if behavior not in BEHAVIOR_TYPES:
        raise ValueError(f"{name}: upstream behavior must be domain or ipcidr")
    parser = str(config.get("parser", ""))
    rules: list[Rule] = []
    unsupported: list[str] = []
    if parser == "v2fly-component":
        if behavior != "domain":
            raise ValueError(f"{name}: V2Fly components only support domain behavior")
        components = [str(value) for value in config.get("components", [])]
        if not components:
            raise ValueError(f"{name}: V2Fly component list is empty")
        for component in components:
            rules.extend(parse_v2fly_component(component, v2fly_base, fetcher))
    else:
        urls = [str(value) for value in config.get("urls", [])]
        if not urls:
            raise ValueError(f"{name}: upstream URL list is empty")
        keyword_suffixes = {
            str(value) for value in config.get("keyword_suffixes", [])
        }
        for url in urls:
            body = fetcher.text(url)
            if parser == "meta-list":
                if behavior != "domain":
                    raise ValueError(f"{name}: meta-list only supports domain behavior")
                rules.extend(parse_meta_list(body, url))
            elif parser == "cidr-list":
                if behavior != "ipcidr":
                    raise ValueError(f"{name}: cidr-list only supports ipcidr behavior")
                rules.extend(parse_cidr_list(body, url))
            elif parser == "classical-list":
                parsed, ignored = parse_classical_list(
                    body, url, behavior, keyword_suffixes
                )
                rules.extend(parsed)
                unsupported.extend(ignored)
            else:
                raise ValueError(f"{name}: unsupported upstream parser: {parser}")
    rules = stable_unique(rules)
    if behavior == "domain":
        rules = compact_domains(rules)
    allowed = BEHAVIOR_TYPES[behavior]
    invalid = [rule.classical for rule in rules if rule.kind not in allowed]
    if invalid:
        raise ValueError(f"{name}: {behavior} set contains invalid rules: {invalid[:3]}")
    if not rules:
        raise RuntimeError(f"{name}: upstream set is empty")
    return RuleSet(rules, behavior), unsupported


def stable_unique(rules: list[Rule]) -> list[Rule]:
    return list(dict.fromkeys(rules))


def merge_rule_sets(name: str, manual: RuleSet, upstream: RuleSet) -> RuleSet:
    if manual.behavior != "classical":
        raise ValueError(f"{name}: merge source must be a manual classical set")
    invalid = [
        rule.classical
        for rule in manual.rules
        if rule.kind not in BEHAVIOR_TYPES[upstream.behavior]
    ]
    if invalid:
        raise ValueError(
            f"{name}: manual rules are incompatible with {upstream.behavior}: "
            f"{invalid[:3]}"
        )
    # Keep the literal normalized union. Do not compact exact rules beneath a
    # suffix: merge_manual promises source-level union semantics to reviewers.
    return RuleSet(stable_unique([*manual.rules, *upstream.rules]), upstream.behavior)


def compact_domains(rules: list[Rule]) -> list[Rule]:
    non_domains = [rule for rule in rules if rule.kind not in DOMAIN_TYPES]
    exact = {rule.value for rule in rules if rule.kind == "DOMAIN"}
    suffixes = {rule.value for rule in rules if rule.kind == "DOMAIN-SUFFIX"}

    def covered_by(domain: str, candidates: set[str]) -> bool:
        labels = domain.split(".")
        return any(".".join(labels[index:]) in candidates for index in range(len(labels)))

    kept_suffixes: set[str] = set()
    for domain in sorted(suffixes, key=lambda value: (value.count("."), value)):
        if not covered_by(domain, kept_suffixes):
            kept_suffixes.add(domain)
    exact = {
        domain
        for domain in exact
        if not covered_by(domain, kept_suffixes)
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
    validate_airport_domain_source(name, rules, stage="render")
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


def render_ipcidr_yaml(name: str, rules: list[Rule]) -> str:
    if any(rule.kind not in IP_TYPES for rule in rules):
        raise ValueError(f"{name}: ipcidr YAML cannot contain non-IP rules")
    lines = [
        "# AUTO-GENERATED. DO NOT EDIT.",
        f"# Rule set: {name}",
        "payload:",
    ]
    lines.extend(f"  - {rule.ip_token}" for rule in rules)
    return "\n".join(lines) + "\n"


def render_list(name: str, rules: list[Rule], behavior: str = "classical") -> str:
    validate_airport_domain_source(name, rules, stage="render")
    lines = [
        "# AUTO-GENERATED. DO NOT EDIT.",
        f"# Rule set: {name}",
    ]
    if behavior == "ipcidr":
        lines.extend(f"{rule.classical},no-resolve" for rule in rules)
    else:
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


def parse_list_rules(path: Path, behavior: str = "classical") -> list[Rule]:
    rules: list[Rule] = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if behavior == "ipcidr":
            parts = [part.strip() for part in line.split(",")]
            if len(parts) not in {2, 3} or parts[0] not in IP_TYPES:
                raise ValueError(f"Unsupported generated IP list rule in {path}: {line}")
            if len(parts) == 3 and parts[2] != "no-resolve":
                raise ValueError(f"Unsupported generated IP option in {path}: {line}")
            rules.append(normalize_ip_network(parts[1]))
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


def compile_mrs(mihomo: Path, source: Path, target: Path, behavior: str) -> None:
    if behavior not in BEHAVIOR_TYPES:
        raise ValueError(f"Unsupported MRS behavior: {behavior}")
    target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [str(mihomo), "convert-ruleset", behavior, "yaml", str(source), str(target)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or not target.exists() or target.stat().st_size == 0:
        raise RuntimeError(f"MRS compile failed for {source}: {result.stdout}{result.stderr}")
    with tempfile.TemporaryDirectory(prefix="customrules-mrs-") as temporary:
        roundtrip = Path(temporary) / "roundtrip.txt"
        result = subprocess.run(
            [str(mihomo), "convert-ruleset", behavior, "mrs", str(target), str(roundtrip)],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0 or not roundtrip.exists():
            raise RuntimeError(f"MRS round-trip failed for {target}: {result.stdout}{result.stderr}")
        if behavior == "domain":
            expected_rules = parse_domain_yaml(source)
            actual_rules = [
                Rule(
                    "DOMAIN-SUFFIX" if line.strip().startswith("+.") else "DOMAIN",
                    normalize_domain(
                        line.strip()[2:]
                        if line.strip().startswith("+.")
                        else line.strip()
                    ),
                )
                for line in roundtrip.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            if set(compact_domains(expected_rules)) != set(
                compact_domains(actual_rules)
            ):
                raise RuntimeError(f"MRS domain-semantics mismatch for {target}")
        else:
            expected_rules = parse_ipcidr_yaml(source)
            actual_rules = [
                normalize_ip_network(line)
                for line in roundtrip.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            if canonical_ip_networks(expected_rules) != canonical_ip_networks(
                actual_rules
            ):
                raise RuntimeError(f"MRS address-space mismatch for {target}")


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


def parse_ipcidr_yaml(path: Path) -> list[Rule]:
    rules: list[Rule] = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line.startswith("- "):
            continue
        rules.append(normalize_ip_network(line[2:].strip()))
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
    sets: dict[str, RuleSet] = {}
    unsupported_upstream_rules: list[str] = []
    entity_reports: dict[str, list[dict[str, object]]] = {}

    for path in sorted((SOURCES / "manual").glob("*.yaml")):
        rules = parse_classical_yaml(path)
        validate_airport_domain_source(path.stem, rules)
        sets[path.stem] = RuleSet(rules, "classical")

    for name, config in sorted(upstream_config.get("sets", {}).items()):
        built, unsupported = build_upstream_set(
            name, dict(config), v2fly_base, fetcher
        )
        unsupported_upstream_rules.extend(unsupported)
        existing = sets.get(name)
        if existing is not None:
            if not bool(config.get("merge_manual", False)):
                raise ValueError(
                    f"{name}: upstream set collides with manual source without merge_manual"
                )
            built = merge_rule_sets(name, existing, built)
        sets[name] = built

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
    sets["Crypto"] = RuleSet(crypto, "domain")

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
    sets["Banking"] = RuleSet(banking, "domain")
    union = set().union(*(set(value) for value in regions.values()))
    if union != set(banking):
        raise RuntimeError("Banking region union does not equal Banking aggregate")
    validate_region_exclusivity(regions)

    manifests: dict[str, dict[str, object]] = {}
    for name, rule_set in sorted(sets.items()):
        rules = stable_unique(rule_set.rules)
        validate_airport_domain_source(name, rules, stage="build")
        behavior = rule_set.behavior
        is_domain_only = all(rule.kind in DOMAIN_TYPES for rule in rules)
        yaml_path = args.output / "Mihomo" / f"{name}.yaml"
        list_path = args.output / "Surge" / f"{name}.list"
        if behavior == "domain":
            write_text(yaml_path, render_domain_yaml(name, rules))
            yaml_rules = parse_domain_yaml(yaml_path)
        elif behavior == "ipcidr":
            write_text(yaml_path, render_ipcidr_yaml(name, rules))
            yaml_rules = parse_ipcidr_yaml(yaml_path)
        else:
            write_text(yaml_path, render_classical_yaml(name, rules))
            yaml_rules = parse_classical_yaml(yaml_path)
        validate_airport_domain_source(name, yaml_rules, stage="YAML output")
        write_text(list_path, render_list(name, rules, behavior))
        list_rules = parse_list_rules(list_path, behavior)
        validate_airport_domain_source(name, list_rules, stage="LIST output")
        if yaml_rules != list_rules:
            raise RuntimeError(f"YAML/LIST mismatch for {name}")
        formats = ["yaml", "list"]
        mrs_behavior: str | None = None
        if behavior in BEHAVIOR_TYPES:
            compile_source = yaml_path
            mrs_behavior = behavior
        elif is_domain_only:
            compile_source = args.output / ".compile" / f"{name}.yaml"
            write_text(compile_source, render_domain_yaml(name, rules))
            mrs_behavior = "domain"
        if mrs_behavior:
            compile_mrs(
                args.mihomo,
                compile_source,
                args.output / "Mihomo" / f"{name}.mrs",
                mrs_behavior,
            )
            formats.append("mrs")
        manifests[name] = {
            "rule_count": len(rules),
            "behavior": behavior,
            "formats": formats,
            "rules_sha256": hashlib.sha256(
                "\n".join(rule.classical for rule in rules).encode()
            ).hexdigest(),
        }
        if mrs_behavior:
            manifests[name]["mrs_behavior"] = mrs_behavior

    for region, rules in regions.items():
        name = f"Banking/{region}"
        yaml_path = args.output / "Mihomo" / "Banking" / f"{region}.yaml"
        list_path = args.output / "Surge" / "Banking" / f"{region}.list"
        write_text(yaml_path, render_domain_yaml(name, rules))
        write_text(list_path, render_list(name, rules, "domain"))
        if parse_domain_yaml(yaml_path) != parse_list_rules(list_path):
            raise RuntimeError(f"YAML/LIST mismatch for {name}")
        compile_mrs(
            args.mihomo,
            yaml_path,
            args.output / "Mihomo" / "Banking" / f"{region}.mrs",
            "domain",
        )
        manifests[name] = {
            "rule_count": len(rules),
            "behavior": "domain",
            "formats": ["yaml", "list", "mrs"],
            "mrs_behavior": "domain",
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
    write_text(
        args.output / "reports" / "Unsupported-Upstream-Rules.txt",
        "\n".join(
            [
                "# AUTO-GENERATED REVIEW REPORT. NOT USED FOR ROUTING.",
                "# Unsupported classical rules excluded from domain/ipcidr artifacts.",
                *sorted(set(unsupported_upstream_rules)),
                "",
            ]
        ),
    )

    shutil.rmtree(args.output / ".compile", ignore_errors=True)
    manifest = {
        "schema": 2,
        "branch": "auto-build",
        "source_commit": args.source_commit,
        "mihomo_version": load_toml(SOURCES / "toolchain.toml")["mihomo"]["version"],
        "sets": manifests,
        "entities": entity_reports,
    }
    write_text(args.output / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    write_text(args.output / "SOURCES.json", json.dumps(registry.as_json(), indent=2, sort_keys=True) + "\n")
    write_text(
        args.output / ".gitattributes",
        "# AUTO-GENERATED. DO NOT EDIT.\n"
        "* text=auto eol=lf\n"
        "*.mrs binary\n",
    )

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
