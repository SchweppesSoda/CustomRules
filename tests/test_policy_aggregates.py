from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_rules as build
import verify_build


class PolicyAggregateTests(unittest.TestCase):
    def contract(self, members):
        return {'schema': 1, 'aggregates': {'Policy/GlobalTV': {
            'policy': 'Global TV', 'members': members}}}

    def test_literal_union_preserves_exact_suffix_keywords_and_flags(self):
        r = build.Rule
        exact = r('DOMAIN', 'video.example.com')
        suffix = r('DOMAIN-SUFFIX', 'example.com')
        keyword = r('DOMAIN-KEYWORD', 'video')
        ip = r('IP-CIDR', '192.0.2.0/24,no-resolve')
        sets = {'A': build.RuleSet([exact, suffix], 'domain'),
                'B': build.RuleSet([exact, keyword, ip], 'classical')}
        build.add_policy_aggregates(sets, self.contract(['A', 'B']))
        merged = sets['Policy/GlobalTV']
        self.assertEqual(merged.rules, [exact, suffix, keyword, ip])
        self.assertEqual(merged.behavior, 'classical')
        self.assertEqual(sets['A'].rules, [exact, suffix])

    def test_pure_domain_and_ip_can_use_mrs_without_losing_rules(self):
        for kind, value, behavior in [('DOMAIN', 'a.example', 'domain'),
                                      ('IP-CIDR', '192.0.2.0/24', 'ipcidr')]:
            with self.subTest(behavior=behavior):
                sets = {name: build.RuleSet([build.Rule(kind, value)], 'ipcidr' if kind=='IP-CIDR' else 'classical')
                        for name in ('A', 'B')}
                build.add_policy_aggregates(sets, self.contract(['A', 'B']))
                self.assertEqual(sets['Policy/GlobalTV'].behavior, behavior)
                self.assertEqual(len(sets['Policy/GlobalTV'].rules), 1)

    def test_classical_ip_options_are_not_coerced_to_ipcidr(self):
        rule = build.Rule('IP-CIDR', '192.0.2.0/24,no-resolve')
        sets = {name: build.RuleSet([rule], 'classical') for name in ('A', 'B')}
        build.add_policy_aggregates(sets, self.contract(['A', 'B']))
        self.assertEqual(sets['Policy/GlobalTV'].behavior, 'classical')
        self.assertEqual(sets['Policy/GlobalTV'].rules, [rule])

    def test_bad_member_contracts_fail_before_mutation(self):
        for members in [['A', 'A'], ['A', 'missing'], ['A'], ['A', 'Policy/Other']]:
            sets = {'A': build.RuleSet([build.Rule('DOMAIN', 'a.example')], 'domain')}
            with self.subTest(members=members), self.assertRaises(ValueError):
                build.add_policy_aggregates(sets, self.contract(members))
            self.assertEqual(list(sets), ['A'])
        sets['B'] = build.RuleSet([build.Rule('DOMAIN', 'b.example')], 'domain')
        contract = self.contract(['A', 'B'])
        contract['aggregates']['Policy/Bad'] = {'policy': 'Other', 'members': ['A', 'missing']}
        with self.assertRaises(ValueError):
            build.add_policy_aggregates(sets, contract)
        self.assertEqual(set(sets), {'A', 'B'})

    def test_validator_rejects_dropped_or_added_rules_and_wrong_members(self):
        r = build.Rule
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sets = {'A': build.RuleSet([r('DOMAIN', 'a.example')], 'domain'),
                    'B': build.RuleSet([r('DOMAIN-KEYWORD', 'video')], 'classical')}
            contract = self.contract(['A', 'B'])
            metadata = build.add_policy_aggregates(sets, contract)
            manifest = {'sets': {name: {'behavior': rules.behavior}
                                 for name, rules in sets.items()}}
            manifest['sets']['Policy/GlobalTV']['aggregation'] = metadata['Policy/GlobalTV']
            for name, rules in sets.items():
                build.write_text(root/'Surge'/f'{name}.list', build.render_list(name, rules.rules, rules.behavior))
            with patch.object(verify_build, 'load_toml', return_value=contract):
                verify_build.verify_policy_aggregates(root, manifest)
                for changed in [[r('DOMAIN', 'a.example')],
                                sets['Policy/GlobalTV'].rules + [r('DOMAIN', 'new.example')]]:
                    build.write_text(root/'Surge/Policy/GlobalTV.list', build.render_list('Fixture', changed))
                    with self.assertRaisesRegex(RuntimeError, 'literal member union'):
                        verify_build.verify_policy_aggregates(root, manifest)
                manifest['sets']['Policy/GlobalTV']['aggregation']['members'] = ['A']
                with self.assertRaisesRegex(RuntimeError, 'membership mismatch'):
                    verify_build.verify_policy_aggregates(root, manifest)


if __name__ == '__main__':
    unittest.main()
