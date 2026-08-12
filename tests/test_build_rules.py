from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "build_rules", ROOT / "scripts" / "build_rules.py"
)
assert SPEC and SPEC.loader
build_rules = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = build_rules
SPEC.loader.exec_module(build_rules)


class BuildRulesTests(unittest.TestCase):
    def test_cidr_parser_accepts_bare_and_prefixed_networks(self) -> None:
        rules = build_rules.parse_cidr_list(
            "1.2.3.4/24\nIP-CIDR6:2001:db8::1/48\n", "test"
        )
        self.assertEqual(
            [rule.classical for rule in rules],
            ["IP-CIDR,1.2.3.0/24", "IP-CIDR6,2001:db8::/48"],
        )

    def test_mixed_classical_parser_reports_unsupported_types(self) -> None:
        body = "\n".join(
            [
                "DOMAIN-SUFFIX,example.com",
                "IP-CIDR,192.0.2.1/24,no-resolve",
                "USER-AGENT,Example*",
            ]
        )
        domain, domain_unsupported = build_rules.parse_classical_list(
            body, "test", "domain", set()
        )
        ip_rules, ip_unsupported = build_rules.parse_classical_list(
            body, "test", "ipcidr", set()
        )
        self.assertEqual([rule.classical for rule in domain], ["DOMAIN-SUFFIX,example.com"])
        self.assertEqual([rule.classical for rule in ip_rules], ["IP-CIDR,192.0.2.0/24"])
        self.assertEqual(len(domain_unsupported), 1)
        self.assertEqual(len(ip_unsupported), 1)

    def test_ip_canonicalization_accepts_lossless_mrs_aggregation(self) -> None:
        split = [
            build_rules.normalize_ip_network("91.108.8.0/22"),
            build_rules.normalize_ip_network("91.108.12.0/22"),
        ]
        merged = [build_rules.normalize_ip_network("91.108.8.0/21")]
        self.assertEqual(
            build_rules.canonical_ip_networks(split),
            build_rules.canonical_ip_networks(merged),
        )

    def test_manual_merge_is_literal_deduplicated_union(self) -> None:
        manual = build_rules.RuleSet(
            [
                build_rules.Rule("DOMAIN", "emby.example.com"),
                build_rules.Rule("DOMAIN-SUFFIX", "example.com"),
            ],
            "classical",
        )
        upstream = build_rules.RuleSet(
            [
                build_rules.Rule("DOMAIN-SUFFIX", "example.com"),
                build_rules.Rule("DOMAIN", "upstream.example.net"),
            ],
            "domain",
        )
        merged = build_rules.merge_rule_sets("Emby", manual, upstream)
        self.assertEqual(
            [rule.classical for rule in merged.rules],
            [
                "DOMAIN,emby.example.com",
                "DOMAIN-SUFFIX,example.com",
                "DOMAIN,upstream.example.net",
            ],
        )
        self.assertEqual(merged.behavior, "domain")

    def test_domain_canonicalization_removes_only_covered_redundancy(self) -> None:
        rules = [
            build_rules.Rule("DOMAIN", "emby.example.com"),
            build_rules.Rule("DOMAIN-SUFFIX", "example.com"),
            build_rules.Rule("DOMAIN", "independent.example.net"),
        ]
        self.assertEqual(
            [rule.classical for rule in build_rules.compact_domains(rules)],
            [
                "DOMAIN,independent.example.net",
                "DOMAIN-SUFFIX,example.com",
            ],
        )


if __name__ == "__main__":
    unittest.main()
