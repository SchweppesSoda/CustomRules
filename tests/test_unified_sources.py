from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_rules as builder
import verify_consumers


class UnifiedSourcesTests(unittest.TestCase):
    def test_classical_roundtrip_retains_non_domain_semantics(self):
        body = 'DOMAIN-SUFFIX,Example.COM\nDOMAIN-KEYWORD,example\nIP-CIDR,192.0.2.1/24,no-resolve\nIP-ASN,64512,no-resolve\nUSER-AGENT,Example*\nURL-REGEX,^http://example.com/path\n'
        rules = builder.parse_full_classical_list(body, 'fixture')
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            yaml = directory/'rules.yaml'
            listing = directory/'rules.list'
            yaml.write_text(builder.render_classical_yaml('Fixture', rules), encoding='utf-8')
            listing.write_text(builder.render_list('Fixture', rules), encoding='utf-8')
            self.assertEqual(builder.parse_classical_yaml(yaml), rules)
            self.assertEqual(builder.parse_list_rules(listing), rules)
        self.assertIn(builder.Rule('IP-CIDR', '192.0.2.0/24,no-resolve'), rules)

    def test_unknown_classical_syntax_fails_instead_of_disappearing(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported classical syntax'):
            builder.parse_full_classical_list('DOMAIN,example.com\nUNKNOWN,value', 'fixture')

    def test_light_wildcards_preserve_root_and_subdomain_coverage(self):
        rules = builder.parse_wildcard_domain_list('# source\n*.Ads.Example.com\n', 'fixture')
        self.assertEqual(rules, [builder.Rule('DOMAIN-SUFFIX', 'ads.example.com')])
        for host in ['ads.example.com', 'sub.ads.example.com']:
            self.assertTrue(builder.rules_overlap(rules[0], builder.Rule('DOMAIN', host)))
        self.assertFalse(builder.rules_overlap(rules[0], builder.Rule('DOMAIN', 'notads.example.com')))

    def test_light_parser_rejects_silent_format_changes(self):
        for body in ['example.com', '||example.com^', '*.com', '*.192.0.2.1',
                     '*.example.com\nDOMAIN-KEYWORD,ads', '*.ads.*.com', '# empty']:
            with self.subTest(body=body), self.assertRaises(ValueError):
                builder.parse_wildcard_domain_list(body, 'fixture')

    def test_lite_follows_upstream_but_protects_httpdns_match_spaces(self):
        rule = builder.Rule
        protected = [rule('DOMAIN', 'httpdns.browser.example'),
                     rule('DOMAIN-SUFFIX', 'dns.example')]
        blocked = [rule('DOMAIN-SUFFIX', 'browser.example'),
                   rule('DOMAIN-SUFFIX', 'dns.example'),
                   rule('DOMAIN', 'child.dns.example')]
        safe = [rule('DOMAIN-SUFFIX', 'new-ad-network.example'),
                rule('DOMAIN-SUFFIX', 'notdns.example'),
                rule('DOMAIN', 'child.httpdns.browser.example')]
        selected, excluded = builder.select_adblock_lite(blocked + safe, protected)
        self.assertEqual(set(selected), set(safe))
        self.assertEqual(len(excluded), 3)
        for candidate in selected:
            self.assertFalse(any(builder.rules_overlap(candidate, p) for p in protected))

    def test_lite_protects_shared_services_and_rejects_non_domains(self):
        rule = builder.Rule
        policy = tomllib.loads((ROOT/'sources/policies/adblock-lite.toml').read_text())
        protected = builder.adblock_lite_protections(policy, [rule('DOMAIN', 'dns.example')])
        safe = rule('DOMAIN-SUFFIX', 'ads.example')
        selected, excluded = builder.select_adblock_lite([
            safe, rule('DOMAIN-SUFFIX', 'onesignal.com'),
            rule('DOMAIN', 'o123.ingest.sentry.io'), rule('DOMAIN-SUFFIX', 'dns.example'),
        ], protected)
        self.assertEqual(selected, [safe])
        self.assertEqual(len(excluded), 3)
        for bad in [rule('DOMAIN-KEYWORD', 'ads'), rule('IP-CIDR', '192.0.2.0/24')]:
            with self.assertRaisesRegex(ValueError, 'domain-only'):
                builder.select_adblock_lite([safe, bad], protected)
        with self.assertRaisesRegex(ValueError, 'no rules'):
            builder.select_adblock_lite([rule('DOMAIN', 'dns.example')], protected)

    def test_offline_snapshot_never_accesses_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            url='https://example.com/source'
            (directory/hashlib.sha256(url.encode()).hexdigest()).write_bytes(b'example.com\n')
            registry=builder.SourceRegistry()
            fetcher=builder.Fetcher(registry,directory,True)
            with patch('urllib.request.urlopen', side_effect=AssertionError('network access')):
                self.assertEqual(fetcher.text(url),'example.com\n')
                with self.assertRaisesRegex(RuntimeError,'snapshot is missing'):
                    fetcher.text('https://example.com/missing')
            self.assertEqual(registry.items[url]['sha256'],hashlib.sha256(b'example.com\n').hexdigest())

    def test_consumer_map_resolves_to_built_set_names(self):
        config=tomllib.loads((ROOT/'sources/upstreams.toml').read_text())
        known=set(config['sets']) | {p.stem for p in (ROOT/'sources/manual').glob('*.yaml')} | {'AdBlockLite','Banking','Crypto'}
        mapping=json.loads((ROOT/'sources/consumer-map.json').read_text())['rules']
        for url,info in mapping.items():
            self.assertIn(info['set'],known,url)
        for name,info in config['sets'].items():
            for included in info.get('include_sets',[]): self.assertIn(included,known,name)

    def test_consumer_scan_excludes_proxy_credentials_and_modules(self):
        text='proxy-providers:\n  node:\n    url: https://private.invalid/sub\nrule-providers:\n  service: { <<: *rp-mrs-domain, url: "'+verify_consumers.BASE+'Mihomo/Discord.mrs" }\n'
        found=list(verify_consumers.subscriptions('Mihomo/AutoMihomo.Mobile.yaml',text))
        self.assertEqual(len(found),1)
        self.assertTrue(found[0][1].endswith('/Discord.mrs'))
        self.assertEqual(list(verify_consumers.subscriptions('Loon/AutoLoon.conf','[Plugin]\nhttps://example.com/plugin.lpx, enabled=true\n')),[])

    def test_consumer_gate_rejects_third_party_and_behavior_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); build=root/'build'; repo=root/'repo'
            (build/'Mihomo').mkdir(parents=True)
            (build/'Mihomo/Fixture.mrs').write_bytes(b'fixture')
            (build/'manifest.json').write_text(json.dumps({'sets':{'Fixture':{'formats':['mrs'],'mrs_behavior':'ipcidr'}}}))
            file=repo/'Mihomo/AutoMihomo.Mobile.yaml'; file.parent.mkdir(parents=True)
            file.write_text('rule-providers:\n  a: { <<: *rp-mrs-domain, url: "'+verify_consumers.BASE+'Mihomo/Fixture.mrs" }\n  b: { url: https://example.com/rule.list }\n')
            _,failures=verify_consumers.verify(repo,build)
            self.assertTrue(any('behavior mismatch' in failure for failure in failures))
            self.assertTrue(any('bypasses CustomRules' in failure for failure in failures))


if __name__ == '__main__': unittest.main()
