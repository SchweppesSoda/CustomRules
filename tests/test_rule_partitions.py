"""Conservative source-local partitions; no fetch, compiler or publication."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_rules as build
import verify_build


class RulePartitionTests(unittest.TestCase):
    def contract(self, *sources):
        return {"schema": 1, "clients": ["Egern"], "sources": list(sources)}

    def mixed_rules(self):
        r = build.Rule
        return [r("DOMAIN", "exact.example"),
                r("IP-CIDR", "192.0.2.0/24,no-resolve"),
                r("DOMAIN-SUFFIX", "example"),
                r("USER-AGENT", "Example%20Player*"),
                r("IP-CIDR6", "2001:db8::/32"),
                r("PROCESS-NAME", "Example Player.exe"),
                r("IP-ASN", "64512,no-resolve"),
                r("URL-REGEX", "^https?:\\/\\/player[0-9]+\\.example\\/"),
                r("DOMAIN-KEYWORD", "player"),
                r("DOMAIN-WILDCARD", "*.example")]

    def test_exact_partition_preserves_order_flags_and_every_non_address_type(self):
        rules = self.mixed_rules()
        original = [*rules, rules[0], rules[1]]
        sets = {"Classical/A": build.RuleSet(original.copy(), "classical")}
        metadata = build.add_rule_partitions(sets, self.contract("Classical/A"))
        non_ip = sets["NonIP/Classical/A"]
        address = sets["Address/Classical/A"]
        self.assertEqual(non_ip.rules, [rules[i] for i in (0, 2, 3, 5, 7, 8, 9)])
        self.assertEqual(address.rules, [rules[i] for i in (1, 4, 6)])
        self.assertEqual(non_ip.behavior, "classical")
        self.assertEqual(address.behavior, "classical")
        self.assertEqual(set(non_ip.rules) | set(address.rules), set(original))
        self.assertFalse(set(non_ip.rules) & set(address.rules))
        self.assertEqual(sets["Classical/A"].rules, original)
        self.assertEqual(metadata["Address/Classical/A"], {
            "source": "Classical/A", "part": "address", "clients": ["Egern"]})

    def test_sources_never_expand_into_each_other(self):
        a, b = build.Rule("DOMAIN-KEYWORD", "only-a"), build.Rule("DOMAIN-KEYWORD", "only-b")
        sets = {"Classical/A": build.RuleSet([a], "classical"),
                "Policy/Classical/B": build.RuleSet([b], "classical")}
        build.add_rule_partitions(sets, self.contract(*sets))
        self.assertEqual(sets["NonIP/Classical/A"].rules, [a])
        self.assertEqual(sets["NonIP/Policy/Classical/B"].rules, [b])
        self.assertEqual(sets["Address/Classical/A"].rules, [])
        self.assertEqual(sets["Address/Policy/Classical/B"].rules, [])

    def test_empty_side_has_explicit_yaml_and_no_fabricated_list_rules(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for rule in (build.Rule("USER-AGENT", "Example*"),
                         build.Rule("IP-CIDR", "192.0.2.0/24")):
                sets = {"Classical/A": build.RuleSet([rule], "classical")}
                build.add_rule_partitions(sets, self.contract("Classical/A"))
                empty = "Address/Classical/A" if rule.kind == "USER-AGENT" else "NonIP/Classical/A"
                self.assertEqual(sets[empty].rules, [])
                yaml, listing = root / "empty.yaml", root / "empty.list"
                build.write_text(yaml, build.render_classical_yaml(empty, []))
                build.write_text(listing, build.render_list(empty, []))
                self.assertIn("payload: []", yaml.read_text())
                self.assertEqual(build.parse_classical_yaml(yaml, allow_empty=True), [])
                self.assertEqual(build.parse_list_rules(listing), [])
                with self.assertRaises(ValueError):
                    build.parse_classical_yaml(yaml)
            yaml.write_text("# missing payload is not an empty partition\n")
            with self.assertRaises(ValueError):
                build.parse_classical_yaml(yaml, allow_empty=True)

    def test_unknown_address_and_compound_syntax_fail_closed(self):
        for kind in ("SRC-IP-CIDR", "SRC-IP-ASN", "GEOIP", "AND", "OR", "NOT", "NEW-TYPE"):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "Unsupported rule partition type"):
                build.split_address_rules([build.Rule(kind, "192.0.2.0/24")])
            line = f"{kind},((DOMAIN,example.com),(IP-CIDR,192.0.2.0/24))"
            with self.subTest(parser=kind), self.assertRaisesRegex(ValueError, "Unsupported classical syntax"):
                build.parse_full_classical_list(line, "public fixture")

    def test_invalid_contracts_and_late_invalid_sources_do_not_mutate(self):
        source = build.RuleSet([build.Rule("DOMAIN-KEYWORD", "fixture")], "classical")
        for contract in ({"schema": 2, "clients": ["Egern"], "sources": ["Classical/A"]},
                         {"schema": 1, "clients": ["Egern", "Stash"], "sources": ["Classical/A"]},
                         self.contract("Classical/A", "Classical/A"),
                         self.contract("Classical/A", "../Classical/B"),
                         self.contract("Classical/A", "Classical/missing")):
            sets = {"Classical/A": source}
            with self.subTest(contract=contract), self.assertRaises(ValueError):
                build.add_rule_partitions(sets, contract)
            self.assertEqual(sets, {"Classical/A": source})
        for bad in ([], [build.Rule("SRC-IP-CIDR", "192.0.2.0/24")]):
            sets = {"Classical/A": source, "Classical/B": build.RuleSet(bad, "classical")}
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                build.add_rule_partitions(sets, self.contract("Classical/A", "Classical/B"))
            self.assertEqual(set(sets), {"Classical/A", "Classical/B"})
        sets = {"Classical/A": source, "Address/Classical/A": source}
        with self.assertRaisesRegex(ValueError, "collides"):
            build.add_rule_partitions(sets, self.contract("Classical/A"))
        self.assertEqual(set(sets), {"Classical/A", "Address/Classical/A"})

    def test_declared_scope_is_exactly_the_seventeen_reviewed_sources(self):
        expected = {"Classical/" + name for name in (
            "OpenAI", "Copilot", "Telegram", "YouTube", "Spotify", "Netflix", "Apple",
            "GlobalMedia", "BiliBili", "ChinaMedia", "GoogleFCM", "Google", "Proxy", "WeChat", "China")}
        expected |= {"Policy/Classical/AsianTV", "Policy/Classical/CNMainlandTV"}
        contract = build.load_toml(build.SOURCES / "rule-partitions.toml")
        self.assertEqual(set(build.rule_partition_sources(contract)), expected)
        upstream = build.load_toml(build.SOURCES / "upstreams.toml")["sets"]
        aggregates = build.load_toml(build.SOURCES / "policy-aggregates.toml")["aggregates"]
        self.assertTrue(expected <= set(upstream) | set(aggregates))

    def fixture(self, root, rules):
        contract = self.contract("Classical/A")
        sets = {"Classical/A": build.RuleSet(rules, "classical")}
        metadata = build.add_rule_partitions(sets, contract)
        manifest = {"sets": {}}
        for name, rule_set in sets.items():
            build.write_text(root / "Surge" / f"{name}.list", build.render_list(name, rule_set.rules))
            build.write_text(root / "Mihomo" / f"{name}.yaml", build.render_classical_yaml(name, rule_set.rules))
            info = {"behavior": rule_set.behavior, "formats": ["yaml", "list"]}
            if name in metadata:
                info["partition"] = metadata[name]
                if rule_set.rules and all(rule.kind in build.DOMAIN_TYPES for rule in rule_set.rules):
                    info["formats"].append("mrs")
                    info["mrs_behavior"] = "domain"
                    (root / "Mihomo" / f"{name}.mrs").write_bytes(b"not a compiled MRS; inventory test only")
            manifest["sets"][name] = info
        return contract, manifest

    def test_verifier_rejects_lost_added_reordered_flags_or_misclassified_rules(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract, manifest = self.fixture(root, self.mixed_rules())
            name = "Address/Classical/A"
            path = root / "Surge" / f"{name}.list"
            original = build.parse_list_rules(path)
            with patch.object(verify_build, "load_toml", return_value=contract):
                verify_build.verify_rule_partitions(root, manifest)
                for mutation in (original[:-1],
                                 original + [build.Rule("IP-CIDR", "198.51.100.0/24")],
                                 list(reversed(original)),
                                 [build.Rule("IP-CIDR", "192.0.2.0/24"), *original[1:]],
                                 original + [build.Rule("USER-AGENT", "Example*")],
                                 original + original[:1]):
                    build.write_text(path, build.render_list(name, mutation))
                    with self.subTest(mutation=mutation), self.assertRaisesRegex(RuntimeError, "literal source subsequence"):
                        verify_build.verify_rule_partitions(root, manifest)

    def test_verifier_requires_both_sides_source_metadata_and_classical_address(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract, manifest = self.fixture(root, [build.Rule("IP-ASN", "64512,no-resolve")])
            with patch.object(verify_build, "load_toml", return_value=contract):
                verify_build.verify_rule_partitions(root, manifest)
                name = "Address/Classical/A"
                info = manifest["sets"].pop(name)
                with self.assertRaisesRegex(RuntimeError, "inventory"):
                    verify_build.verify_rule_partitions(root, manifest)
                manifest["sets"][name] = info
                info["partition"]["source"] = "Classical/Other"
                with self.assertRaisesRegex(RuntimeError, "metadata/behavior"):
                    verify_build.verify_rule_partitions(root, manifest)
                info["partition"]["source"] = "Classical/A"
                info["behavior"] = "ipcidr"
                with self.assertRaisesRegex(RuntimeError, "metadata/behavior"):
                    verify_build.verify_rule_partitions(root, manifest)
                info["behavior"] = "classical"
                info["formats"].append("mrs")
                info["mrs_behavior"] = "ipcidr"
                with self.assertRaisesRegex(RuntimeError, "format/behavior"):
                    verify_build.verify_rule_partitions(root, manifest)

    def test_domain_only_mrs_and_empty_side_inventory_are_checked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract, manifest = self.fixture(root, [build.Rule("DOMAIN", "exact.example")])
            with patch.object(verify_build, "load_toml", return_value=contract):
                verify_build.verify_rule_partitions(root, manifest)
                mrs = root / "Mihomo/NonIP/Classical/A.mrs"
                mrs.unlink()
                with self.assertRaisesRegex(RuntimeError, "format/behavior"):
                    verify_build.verify_rule_partitions(root, manifest)


if __name__ == "__main__":
    unittest.main()
