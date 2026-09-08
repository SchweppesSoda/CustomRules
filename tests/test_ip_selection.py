from __future__ import annotations

import hashlib
import ipaddress
import json
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_rules as builder
import verify_build


class IPSelectionTests(unittest.TestCase):
    def rules(self, *tokens):
        return [builder.normalize_ip_network(token) for token in tokens]

    def test_subtraction_splits_ipv4_ipv6_and_keeps_supplement_after_exclusion(self):
        result = builder.select_ip_union(
            self.rules('192.0.2.0/24', '2001:db8::/126'),
            self.rules('192.0.2.0/25', '2001:db8::/127'),
            self.rules('192.0.2.1/32', '2001:db8::1/128'))
        self.assertEqual(set(r.value for r in result),
                         {'192.0.2.128/25', '192.0.2.1/32', '2001:db8::2/127', '2001:db8::1/128'})
        self.assertEqual(builder.subtract_ip_rules(self.rules('192.0.2.0/24'),
                                                   self.rules('192.0.0.0/16')), [])

    def test_difference_matches_independent_small_address_set_oracle(self):
        rng = random.Random(19)
        for version, base in ((4, '192.0.2.0'), (6, '2001:db8::')):
            address = ipaddress.ip_address(base)
            width = address.max_prefixlen
            for _ in range(30):
                groups = [[ipaddress.ip_network(f'{address + rng.randrange(256)}/{width - rng.randrange(5)}', strict=False)
                           for _ in range(12)] for _ in range(3)]
                expected = (set().union(*(set(n) for n in groups[0])) -
                            set().union(*(set(n) for n in groups[1]))) | set().union(*(set(n) for n in groups[2]))
                selected = builder.select_ip_union(*(self.rules(*map(str, group)) for group in groups))
                actual = set().union(*(set(ipaddress.ip_network(rule.value)) for rule in selected))
                self.assertEqual(actual, expected, f'IPv{version}')

    def fixture(self, root):
        prefix = 'https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/'
        config = {'behavior': 'ipcidr', 'parser': 'cidr-union-excluding',
                  'snapshot_api_url': 'https://api.github.com/repos/MetaCubeX/meta-rules-dat/commits/meta',
                  'urls': [prefix + 'geo/geoip/google.list'],
                  'exclude_urls': [prefix + 'geo/geoip/cn.list'],
                  'supplement_urls': ['https://raw.githubusercontent.com/666OS/rules/release/mihomo/ip/Proxy.txt']}
        sha = '1' * 40
        bodies = {config['snapshot_api_url']: json.dumps({'sha': sha}),
                  config['urls'][0].replace('/meta/', f'/{sha}/'): '192.0.2.0/24\n2001:db8::/126\n',
                  config['exclude_urls'][0].replace('/meta/', f'/{sha}/'): '192.0.2.0/25\n',
                  config['supplement_urls'][0]: '192.0.2.1/32\n'}
        for url, body in bodies.items():
            (root / hashlib.sha256(url.encode()).hexdigest()).write_bytes(body.encode())
        return config, builder.Fetcher(builder.SourceRegistry(), root, True)

    def test_pinned_snapshot_offline_replay_and_failure_guards(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, fetcher = self.fixture(root)
            with patch('urllib.request.urlopen', side_effect=AssertionError('network access')):
                built, _ = builder.build_upstream_set('IP/Proxy', config, '', fetcher)
            self.assertEqual(built.selection['snapshot_commit'], '1' * 40)
            for item in built.selection['sources'][:2]:
                self.assertIn('/' + '1' * 40 + '/', item['url'])
            self.assertEqual(len(built.rules), 3)
            for override in ({'exclude_urls': []}, {'behavior': 'domain'}, {'include_sets': ['IP/Google']},
                             {'urls': ['https://example.com/other']}):
                with self.subTest(override=override), self.assertRaises(ValueError):
                    builder.build_ip_union(dict(config, **override), fetcher)
            (root / hashlib.sha256(config['supplement_urls'][0].encode()).hexdigest()).unlink()
            with self.assertRaisesRegex(RuntimeError, 'snapshot is missing'):
                builder.build_ip_union(config, builder.Fetcher(builder.SourceRegistry(), root, True))

    def test_non_ip_and_unknown_options_fail_closed(self):
        for text in ('DOMAIN,example.com', 'IP-CIDR,192.0.2.0/24,PROXY', '# empty'):
            with self.subTest(text=text), self.assertRaises((ValueError, RuntimeError)):
                builder.parse_cidr_list(text, 'fixture')
        with self.assertRaises(ValueError):
            builder.select_ip_union([builder.Rule('DOMAIN', 'example.com')], [], [])

    def test_no_resolve_verifier_rejects_removed_flag(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'Proxy.list'
            path.write_text(builder.render_list('IP/Proxy', self.rules('192.0.2.0/24', '2001:db8::/32'), 'ipcidr'))
            self.assertEqual(len(verify_build.list_rules(path, 'ipcidr')), 2)
            path.write_text(path.read_text().replace(',no-resolve', '', 1))
            with self.assertRaisesRegex(RuntimeError, 'missing no-resolve'):
                verify_build.list_rules(path, 'ipcidr')

    def test_report_verifies_exact_union_and_input_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, fetcher = self.fixture(root)
            built = builder.build_ip_union(config, fetcher)
            report = root / 'reports/IP/Proxy-selection.json'
            listing = root / 'Surge/IP/Proxy.list'
            builder.write_text(report, json.dumps(built.selection))
            builder.write_text(listing, builder.render_list('IP/Proxy', built.rules, 'ipcidr'))
            builder.write_text(root / 'SOURCES.json', json.dumps(fetcher.registry.as_json()))
            manifest = {'sets': {'IP/Proxy': {'ip_selection': 'reports/IP/Proxy-selection.json'}}}
            with patch.object(verify_build, 'load_toml', return_value={'sets': {'IP/Proxy': config}}):
                verify_build.verify_ip_selections(root, manifest)
                listing.write_text(listing.read_text() + 'IP-CIDR,203.0.113.0/24,no-resolve\n')
                with self.assertRaisesRegex(RuntimeError, 'differs from'):
                    verify_build.verify_ip_selections(root, manifest)
                built.selection['sources'][0]['text'] += '203.0.113.0/24\n'
                report.write_text(json.dumps(built.selection))
                with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                    verify_build.verify_ip_selections(root, manifest)


if __name__ == '__main__':
    unittest.main()
