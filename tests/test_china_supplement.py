import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_rules as builder
import verify_build as verifier


def suffix(value):
    return builder.Rule('DOMAIN-SUFFIX', value)


class ChinaSupplementTests(unittest.TestCase):
    def select(self, base=(), candidates=(), guards=(), protections=(), excluded=()):
        return builder.select_china_supplement(list(base), list(candidates), list(guards),
            list(protections), {'excluded_suffixes': list(excluded)})

    def test_exact_is_not_suffix_coverage(self):
        exact = builder.Rule('DOMAIN', 'example.com')
        selected, _ = self.select(base=[exact], candidates=[exact, suffix('example.com')])
        self.assertEqual(selected, [suffix('example.com')])
        self.assertEqual(self.select(base=[suffix('example.com')],
                                    candidates=[exact, suffix('child.example.com')]), ([], []))

    def test_protected_children_and_label_boundaries(self):
        for child in [builder.Rule('DOMAIN', 'dns.example.com'), suffix('ads.example.com')]:
            with self.subTest(child=child):
                selected, rejected = self.select(candidates=[suffix('example.com'), suffix('ample.com')],
                                                 protections=[child])
                self.assertEqual(selected, [suffix('ample.com')])
                self.assertEqual(rejected[0]['rule'], 'DOMAIN-SUFFIX,example.com')
        self.assertEqual(self.select(candidates=[builder.Rule('DOMAIN', 'example.com')],
                                    protections=[suffix('ads.example.com')])[0],
                         [builder.Rule('DOMAIN', 'example.com')])

    def test_keyword_and_wildcard_protections(self):
        selected, _ = self.select(candidates=[suffix('datadoghq.com'), suffix('my-payments.com'),
                                              suffix('safe.example')],
            protections=[builder.Rule('DOMAIN-WILDCARD', 'intake-*.datadoghq.com'),
                         builder.Rule('DOMAIN-KEYWORD', 'payments')])
        self.assertEqual(selected, [suffix('safe.example')])

    def test_partial_label_wildcard_does_not_protect_every_com_domain(self):
        selected, rejected = self.select(candidates=[suffix('unrelated.com'), suffix('browser-intake-us5-datadoghq.com'),
                                                     suffix('datadoghq.com')],
            protections=[builder.Rule('DOMAIN-WILDCARD', '*.browser-intake-*-datadoghq.com')])
        self.assertEqual(selected, [suffix('unrelated.com'), suffix('datadoghq.com')])
        self.assertEqual(len(rejected), 1)

    def test_negative_guards_and_base_preservation(self):
        base = [suffix('already.cn')]
        selected, rejected = self.select(base=base,
            candidates=[*base, suffix('foreign.example'), suffix('parent.example'), suffix('deferred.example')],
            guards=[suffix('foreign.example'), suffix('ads.parent.example')], excluded=['deferred.example'])
        self.assertEqual(selected, [])
        self.assertEqual(len(rejected), 3)
        self.assertEqual(builder.compact_domains([*base, *selected]), base)

    def test_duplicates_and_zero_increment(self):
        self.assertEqual(self.select(candidates=[suffix('new.example')] * 2)[0], [suffix('new.example')])
        self.assertEqual(self.select(base=[suffix('example')], candidates=[suffix('new.example')]), ([], []))

    def fixture(self, root):
        config = {'snapshot_api_url': 'https://api.github.com/repos/MetaCubeX/meta-rules-dat/commits/meta',
                  'candidates': ['service'], 'overseas': ['service@!cn'], 'ads': ['service@ads']}
        commit = '1' * 40
        bodies = {config['snapshot_api_url']: json.dumps({'sha': commit}).encode()}
        for _, name in builder.china_source_contract(config):
            url = f'https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/{commit}/geo/geosite/{name}.list'
            bodies[url] = {'cn': b'+.base.cn\n', 'service': b'+.new.cn\n+.foreign.example\n',
                          'service@!cn': b'+.foreign.example\n', 'service@ads': b'+.ads.example\n'}[name]
        for url, body in bodies.items():
            (root / hashlib.sha256(url.encode()).hexdigest()).write_bytes(body)
        return config, bodies

    def test_immutable_snapshot_and_missing_guards_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, bodies = self.fixture(root)
            with patch('urllib.request.urlopen', side_effect=AssertionError('network access')):
                evidence = builder.fetch_china_inputs(config, builder.Fetcher(builder.SourceRegistry(), root, True))
            self.assertTrue(all('/' + '1' * 40 + '/' in item['url'] for item in evidence['sources']))
            url = evidence['sources'][-1]['url']
            path = root / hashlib.sha256(url.encode()).hexdigest()
            for body in [None, b'\n', b'# no supported classifiers\n']:
                if body is None:
                    path.unlink()
                else:
                    path.write_bytes(body)
                with self.subTest(body=body), self.assertRaises(RuntimeError):
                    builder.fetch_china_inputs(config, builder.Fetcher(builder.SourceRegistry(), root, True))

    def test_inheritance_and_verifier_reject_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / 'cache'
            cache.mkdir()
            config, _ = self.fixture(cache)
            registry = builder.SourceRegistry()
            evidence = builder.fetch_china_inputs(config, builder.Fetcher(registry, cache, True))
            sources = root / 'sources'
            (sources / 'policies').mkdir(parents=True)
            (sources / 'policies/china-supplement.toml').write_text(
                'schema = 1\nprotected_sets = ["HTTPDNS"]\nexcluded_suffixes = []\n')
            (sources / 'upstreams.toml').write_text(
                '[china_supplement]\nsnapshot_api_url = ' + json.dumps(config['snapshot_api_url']) + '\n' +
                '\n'.join(key + ' = ' + json.dumps(config[key]) for key in ['candidates', 'overseas', 'ads']) +
                '\n[sets."Classical/China"]\ninclude_sets = ["China"]\nnon_domain_only = true\n')
            upstream = builder.load_toml(sources / 'upstreams.toml')
            non_domain = builder.Rule('DOMAIN-KEYWORD', 'china-keyword')
            sets = {'China': builder.RuleSet([suffix('base.cn')], 'domain'),
                    'HTTPDNS': builder.RuleSet([suffix('dns.example')], 'domain'),
                    'Classical/China': builder.RuleSet([suffix('base.cn'), non_domain], 'classical')}
            with patch.object(builder, 'SOURCES', sources):
                builder.apply_china_supplement(sets, upstream, evidence)
            self.assertIn(non_domain, sets['Classical/China'].rules)
            self.assertEqual(sets['China'].rules, [suffix('base.cn'), suffix('new.cn')])
            for name, rule_set in sets.items():
                builder.write_text(root / 'Surge' / (name + '.list'), builder.render_list(name, rule_set.rules, rule_set.behavior))
            builder.write_text(root / 'SOURCES.json', json.dumps(registry.as_json()))
            report = root / 'reports/China-selection.json'
            builder.write_text(report, json.dumps(sets['China'].selection))
            manifest = {'sets': {name: {'behavior': rule_set.behavior} for name, rule_set in sets.items()}}
            manifest['sets']['China']['domain_selection'] = 'reports/China-selection.json'
            with patch.object(verifier, 'SOURCES', sources):
                verifier.verify_china_selection(root, manifest)
                original = sets['China'].selection
                for key, value in [('selected', []), ('sources', original['sources'][:-1]),
                                   ('policy_sha256', '0' * 64), ('snapshot_commit', '2' * 40)]:
                    tampered = copy.deepcopy(original)
                    tampered[key] = value
                    report.write_text(json.dumps(tampered))
                    with self.subTest(key=key), self.assertRaises(RuntimeError):
                        verifier.verify_china_selection(root, manifest)
                report.write_text(json.dumps(original))
                builder.write_text(root / 'Surge/Classical/China.list', 'DOMAIN-SUFFIX,base.cn\n')
                with self.assertRaisesRegex(RuntimeError, 'inheritance'):
                    verifier.verify_china_selection(root, manifest)


if __name__ == '__main__':
    unittest.main()
