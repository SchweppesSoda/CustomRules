#!/usr/bin/env python3
"""Build portable Mihomo and Surge rule sets from MetaCubeX geosite lists."""

from __future__ import annotations

import re
import tempfile
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIHOMO_DIR = ROOT / "Mihomo"

META_BASE = (
    "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/"
    "meta/geo/geosite"
)

RULE_SETS = {
    "AI": (
        f"{META_BASE}/category-ai-!cn.list",
        f"{META_BASE}/apple-intelligence.list",
    ),
    "AppleTV": (f"{META_BASE}/apple-tvplus.list",),
    "AppleCN": (f"{META_BASE}/apple@cn.list",),
    "Apple": (f"{META_BASE}/apple.list",),
}

DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?"
    r"(?:\.[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?)*$",
    re.IGNORECASE,
)


def fetch(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "CustomRules-Upstream-Sync/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8-sig")
    if not body.strip():
        raise RuntimeError(f"Upstream returned an empty response: {url}")
    return body


def parse_domains(body: str, url: str) -> list[str]:
    tokens: list[str] = []
    for line in body.splitlines():
        content = line.split("#", 1)[0]
        tokens.extend(content.split())

    rules: list[str] = []
    for token in tokens:
        if token.startswith("+."):
            rule_type = "DOMAIN-SUFFIX"
            domain = token[2:]
        else:
            rule_type = "DOMAIN"
            domain = token

        domain = domain.rstrip(".").lower()
        if not DOMAIN_RE.fullmatch(domain):
            raise RuntimeError(f"Unsupported geosite token {token!r} from {url}")
        rules.append(f"{rule_type},{domain}")

    if not rules:
        raise RuntimeError(f"No usable domains found in upstream: {url}")
    return rules


def render(name: str, sources: tuple[str, ...]) -> str:
    rules: list[str] = []
    seen: set[str] = set()
    for source in sources:
        for rule in parse_domains(fetch(source), source):
            if rule not in seen:
                seen.add(rule)
                rules.append(rule)

    if not rules:
        raise RuntimeError(f"Generated rule set is empty: {name}")

    source_comments = "\n".join(f"#   - {source}" for source in sources)
    payload = "\n".join(f"  - {rule}" for rule in rules)
    return (
        "# AUTO-GENERATED. DO NOT EDIT.\n"
        "# Sources:\n"
        f"{source_comments}\n"
        "payload:\n"
        f"{payload}\n"
    )


def write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="\n",
        dir=path.parent,
        delete=False,
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(path)
    return True


def main() -> None:
    rendered = {
        name: render(name, sources)
        for name, sources in RULE_SETS.items()
    }

    changed: list[str] = []
    for name, content in rendered.items():
        path = MIHOMO_DIR / f"{name}.yaml"
        if write_if_changed(path, content):
            changed.append(path.relative_to(ROOT).as_posix())

    if changed:
        print("Updated:")
        for path in changed:
            print(f"  {path}")
    else:
        print("All generated rule sets are current.")


if __name__ == "__main__":
    main()
