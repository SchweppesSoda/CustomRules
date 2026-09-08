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

    def test_lite_never_promotes_unreviewed_upstream_additions(self):
        policy = tomllib.loads((ROOT/'sources/policies/adblock-lite.toml').read_text())
        approved = set(policy['approved_domains'])
        rules = [builder.Rule('DOMAIN-SUFFIX', 'doubleclick.net'),
                 builder.Rule('DOMAIN-SUFFIX', 'graph.instagram.com'),
                 builder.Rule('DOMAIN-SUFFIX', 'new-ad-network.example'),
                 builder.Rule('DOMAIN-KEYWORD', 'doubleclick.net'),
                 builder.Rule('IP-CIDR', '192.0.2.0/24')]
        self.assertEqual(builder.select_adblock_lite(rules, approved), [rules[0]])
        self.assertTrue(approved.isdisjoint({'onesignal.com','sentry.io','appsflyersdk.com','graph.instagram.com','dns.weixin.qq.com','paydns.wechatpay.cn'}))

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
