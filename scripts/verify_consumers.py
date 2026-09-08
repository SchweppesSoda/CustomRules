#!/usr/bin/env python3
"""Read-only gate: all ordinary client rule subscriptions resolve to this build.

Plugins, scripts, icons, proxy subscriptions and GeoIP/ASN databases are outside
the rule-set publication contract. Never print arbitrary configuration URLs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from urllib.parse import unquote

BASE = 'https://raw.githubusercontent.com/SchweppesSoda/CustomRules/refs/heads/auto-build/'
CANONICAL = ('Mihomo/AutoMihomo.Mobile.yaml', 'Mihomo/AutoMihomo.OpenWrt.yaml',
             'Mihomo/SafeMihomo.yaml', 'Stash/AutoStash.yaml', 'Egern/AutoEgern.yaml',
             'Surge/AutoSurge.conf', 'Loon/AutoLoon.conf', 'Loon/AutoLoonLite.conf')
GENERATED = ('Mihomo/AutoMihomo.OpenWrt-WAN2.yaml', 'Egern/AutoEgern.PO0SH.yaml',
             'Egern/AutoEgern.PO0GZ.yaml', 'Surge/Split Conf/AutoSurge/Rule.dconf')


def subscriptions(relative: str, text: str):
    section = ''
    yaml_rules = False
    provider_context = ''
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith('#'): continue
        if line.startswith('rule-providers:'): yaml_rules = True
        elif yaml_rules and line and not line[0].isspace() and not stripped.startswith('#'): yaml_rules = False
        if line.startswith('['): section = line.strip()
        if relative.startswith('Egern/'):
            active = bool(re.match(r'\s+match:\s*["\x27]?https://', line))
        elif relative.endswith('.yaml'):
            active = yaml_rules
        else:
            active = section in {'[Rule]', '[Remote Rule]'}
        if yaml_rules and re.match(r'^  [^ ]',line): provider_context = line
        elif yaml_rules: provider_context += '\n' + line
        if active:
            for url in re.findall(r'https://[^\s"\x27,}]+', line):
                yield number, url, provider_context


def verify(repo: Path, output: Path, generated: bool = False):
    manifest=json.loads((output/'manifest.json').read_text(encoding='utf-8'))
    checked=0
    failures=[]
    paths=CANONICAL+(GENERATED if generated else ())
    for relative in paths:
        file=repo/relative
        if not file.is_file():
            failures.append(f'{relative}: missing profile')
            continue
        for number,url,context in subscriptions(relative,file.read_text(encoding='utf-8-sig')):
            label=f'{relative}:{number}'
            if not url.startswith(BASE):
                failures.append(label+': rule subscription bypasses CustomRules')
                continue
            artifact=unquote(url[len(BASE):])
            path=Path(artifact)
            if path.is_absolute() or '..' in path.parts or len(path.parts)<2:
                failures.append(label+': invalid artifact path'); continue
            name=Path(*path.parts[1:]).with_suffix('').as_posix()
            extension=path.suffix.removeprefix('.')
            info=manifest['sets'].get(name,{})
            if extension not in info.get('formats',[]) or not (output/path).is_file():
                failures.append(label+': artifact missing from verified build'); continue
            if extension=='mrs':
                expected='ipcidr' if 'rp-mrs-ipcidr' in context else 'domain'
                if info.get('mrs_behavior')!=expected:
                    failures.append(label+': MRS behavior mismatch')
            if extension=='yaml' and 'rp-classical' in context and info.get('behavior')!='classical':
                failures.append(label+': classical provider points to non-classical YAML')
            checked+=1
    return checked,failures


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--proxyconfig-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--include-generated',action='store_true')
    args=parser.parse_args()
    count,failures=verify(args.proxyconfig_root,args.output,args.include_generated)
    print(f'Checked {count} rule subscriptions; failures={len(failures)}; generated={args.include_generated}')
    for failure in failures: print(failure)
    raise SystemExit(bool(failures))


if __name__=='__main__': main()
