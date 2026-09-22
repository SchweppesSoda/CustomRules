"""Synthetic public inputs only; no compiler execution, fetch or publication."""
import contextlib
import hashlib
import importlib.util
import json
import io
from pathlib import Path
import shutil
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_evidence as evidence
SPEC = importlib.util.spec_from_file_location("evidence_builder", ROOT / "scripts/build_rules.py")
builder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = builder
SPEC.loader.exec_module(builder)
URL = "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/wildcard/light.txt"


class BuildEvidenceTests(unittest.TestCase):
    def test_current_upstream_declarations_are_public_whitelisted(self):
        def urls(value):
            if isinstance(value, dict):
                for nested in value.values():
                    yield from urls(nested)
            elif isinstance(value, list):
                for nested in value:
                    yield from urls(nested)
            elif isinstance(value, str) and value.startswith("https://"):
                yield value
        declared = set(urls(tomllib.loads((ROOT / "sources/upstreams.toml").read_text())))
        self.assertTrue(declared)
        self.assertTrue(all(evidence.public_url(url) for url in declared))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        for relative in ("scripts/build_rules.py", "scripts/verify_build.py", "scripts/build_evidence.py", "sources/toolchain.toml"):
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((ROOT / relative).read_bytes())
        self.cache = self.root / "cache"
        self.cache.mkdir()
        self.compiler = self.root / "never-executed-compiler"
        self.compiler.write_bytes(b"synthetic compiler identity only\n")
        self.baseline = self.root / "baseline"
        self.candidate = self.root / "candidate"
        self.candidate.mkdir()
        self.archive = self.root / "archive"
        self.body = b"*.ads.example\n*.track.example\n"
        self.cache_key = hashlib.sha256(URL.encode()).hexdigest()
        (self.cache / self.cache_key).write_bytes(self.body)
        self.registry = builder.SourceRegistry(self.cache / "SOURCES.json")
        self.fetcher = builder.Fetcher(self.registry, self.cache, offline=True)
        with patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")):
            self.fetcher.bytes(URL)
        self.rules = builder.parse_wildcard_domain_list(self.body.decode(), URL)
        self.write_baseline(self.rules)

    def write_baseline(self, rules):
        path = self.baseline / "Surge/AdBlockLite.list"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(builder.render_list("AdBlockLite", rules), encoding="utf-8")
        (self.baseline / "SOURCES.json").write_text(json.dumps(self.registry.as_json()), encoding="utf-8")
        (self.baseline / "manifest.json").write_text(json.dumps({"sets": {"AdBlockLite": {"rule_count": len(rules)}}}), encoding="utf-8")

    def capture(self, outcome="success"):
        return evidence.capture(source=self.source, cache=self.cache, baseline=self.baseline,
            candidate=self.candidate, compiler=self.compiler, source_commit="a" * 40,
            baseline_commit="b" * 40, outcome=outcome, destination=self.archive)

    def replay(self, name):
        destination = self.root / name
        evidence.restore(self.archive, destination, self.compiler)
        registry = builder.SourceRegistry()
        fetcher = builder.Fetcher(registry, destination / "source-snapshot", offline=True)
        with patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")), patch("subprocess.run", side_effect=AssertionError("compiler forbidden")):
            rules = builder.parse_wildcard_domain_list(fetcher.text(URL), URL)
            output = destination / "output/Surge/AdBlockLite.list"
            output.parent.mkdir(parents=True)
            output.write_text(builder.render_list("AdBlockLite", rules), encoding="utf-8")
            try:
                builder.enforce_baseline(destination / "output", destination / "baseline", False)
            except RuntimeError as error:
                return output.read_bytes(), str(error)
            return output.read_bytes(), "passed"

    def test_success_archive_replays_twice_identically_without_network_or_compiler(self):
        metadata = self.capture()
        self.assertEqual(metadata["compiler"]["binary_sha256"], evidence.digest(self.compiler.read_bytes()))
        self.assertEqual(self.replay("first"), self.replay("second"))
        self.assertEqual(self.replay("third")[1], "passed")

    def test_threshold_failure_keeps_pre_manifest_inputs_and_replays_failure(self):
        self.write_baseline(self.rules + [builder.Rule("DOMAIN-SUFFIX", "old.example")])
        self.capture("failure")
        self.assertFalse((self.archive / "candidate/SOURCES.json").exists())
        first, second = self.replay("first"), self.replay("second")
        self.assertEqual(first, second)
        self.assertIn("Safety threshold", first[1])
        self.assertIn("33.3%", first[1])
        # The original explicit override contract remains unchanged.
        builder.enforce_baseline(self.root / "first/output", self.root / "first/baseline", True)

    def test_parser_failure_has_journal_before_final_sources(self):
        bad = b"not a wildcard rule with spaces\n"
        (self.cache / self.cache_key).write_bytes(bad)
        registry = builder.SourceRegistry(self.cache / "SOURCES.json")
        fetcher = builder.Fetcher(registry, self.cache, offline=True)
        with self.assertRaises(ValueError):
            builder.parse_wildcard_domain_list(fetcher.text(URL), URL)
        self.capture("failure")
        document = json.loads((self.archive / "source-snapshot/SOURCES.json").read_text())
        self.assertEqual(document["sources"][0]["sha256"], evidence.digest(bad))

    def test_no_response_does_not_get_fabricated_digest(self):
        fetcher = builder.Fetcher(self.registry, self.cache)
        with patch("urllib.request.urlopen", side_effect=OSError("offline fixture")), patch("time.sleep"):
            with self.assertRaises(RuntimeError):
                fetcher.bytes(URL + ".missing")
        document = json.loads((self.cache / "SOURCES.json").read_text())
        self.assertEqual([item["url"] for item in document["sources"]], [URL])
        self.capture("failure")

    def test_journal_write_failure_preserves_previous_atomic_file(self):
        before = (self.cache / "SOURCES.json").read_bytes()
        with patch.object(builder.os, "replace", side_effect=OSError("injected")):
            with self.assertRaises(OSError):
                self.registry.add(URL + ".other", b"synthetic")
        self.assertEqual(before, (self.cache / "SOURCES.json").read_bytes())
        self.assertEqual([], list(self.cache.glob(".sources-*")))

    def test_second_build_journal_keeps_first_build_inputs(self):
        other = URL + ".other"
        self.registry.add(other, b"another public response")
        next_registry = builder.SourceRegistry(self.cache / "SOURCES.json")
        next_registry.add(URL, self.body)
        document = json.loads((self.cache / "SOURCES.json").read_text())
        self.assertEqual({item["url"] for item in document["sources"]}, {URL, other})
        self.assertEqual({item["url"] for item in next_registry.as_json()["sources"]}, {URL})

    def test_compiler_has_separate_streaming_size_bound(self):
        with patch.object(evidence, "MAX_FILE", 1):
            checksum, size = evidence.compiler_identity(self.compiler)
        self.assertEqual(checksum, evidence.digest(self.compiler.read_bytes()))
        self.assertEqual(size, self.compiler.stat().st_size)
        with patch.object(evidence, "MAX_COMPILER", 1):
            with self.assertRaises(ValueError):
                evidence.compiler_identity(self.compiler)

    def test_missing_or_corrupt_cache_refuses_archive(self):
        for mutation in (None, b"tampered"):
            with self.subTest(mutation=mutation):
                path = self.cache / self.cache_key
                if mutation is None:
                    path.unlink()
                else:
                    path.write_bytes(mutation)
                with self.assertRaises(ValueError):
                    self.capture()
                self.assertFalse(self.archive.exists())

    def test_private_or_capability_urls_are_rejected(self):
        for url in ("https://subs.example/s/private", URL + "?token=secret", URL + "#token", "https://user:secret@raw.githubusercontent.com/hagezi/dns-blocklists/main/wildcard/light.txt"):
            with self.subTest(url=url):
                self.assertFalse(evidence.public_url(url))
                journal = {"sources": [{"url": url, "sha256": evidence.digest(self.body), "size": str(len(self.body))}]}
                (self.cache / "SOURCES.json").write_text(json.dumps(journal))
                with self.assertRaises(ValueError):
                    self.capture()
                self.assertFalse(self.archive.exists())

    def test_corrupt_missing_extra_archive_and_wrong_compiler_rejected_before_restore(self):
        self.capture()
        archived = self.archive / "source-snapshot" / self.cache_key
        original = archived.read_bytes()
        archived.write_bytes(b"bad")
        with self.assertRaises(ValueError):
            evidence.restore(self.archive, self.root / "bad", self.compiler)
        archived.unlink()
        with self.assertRaises(ValueError):
            evidence.verify(self.archive)
        archived.write_bytes(original)
        (self.archive / "private.key").write_text("synthetic-secret")
        with self.assertRaises(ValueError):
            evidence.verify(self.archive)
        (self.archive / "private.key").unlink()
        self.compiler.write_bytes(b"different")
        with self.assertRaises(ValueError):
            evidence.restore(self.archive, self.root / "bad", self.compiler)
        self.assertFalse((self.root / "bad").exists())

    def test_incomplete_baseline_and_size_limits_fail_before_archive(self):
        path = self.baseline / "Surge/AdBlockLite.list"
        path.unlink()
        with self.assertRaises(ValueError):
            self.capture()
        self.write_baseline(self.rules)
        with patch.object(evidence, "MAX_TOTAL", 4):
            with self.assertRaises(ValueError):
                self.capture()
        self.assertFalse(self.archive.exists())

    def test_no_directory_overwrite_and_no_unlisted_cache_copy(self):
        (self.cache / "private.key").write_text("synthetic-secret")
        self.capture()
        self.assertFalse((self.archive / "source-snapshot/private.key").exists())
        destination = self.root / "preserved"
        destination.mkdir()
        sentinel = destination / "restore-point"
        sentinel.write_text("keep")
        with self.assertRaises(ValueError):
            evidence.restore(self.archive, destination, self.compiler)
        self.assertEqual(sentinel.read_text(), "keep")
        self.assertFalse(any(self.root.glob(".evidence-*")))

    def test_actual_main_text_pipeline_replays_archived_synthetic_inputs_twice(self):
        # Build a complete small source tree with real mandatory-entity and
        # region validation. Nothing uses a real upstream response.
        source_dir = self.source / "sources"
        (source_dir / "manual").mkdir()
        (source_dir / "catalog").mkdir()
        (source_dir / "policies").mkdir()
        (source_dir / "licenses").mkdir()
        (source_dir / "manual/HTTPDNS.yaml").write_text("payload:\n  - DOMAIN,dns.fixture.invalid\n")
        (source_dir / "policies/adblock-lite.toml").write_text('protected_suffixes = ["protected.fixture.invalid"]\n')
        (source_dir / "policy-aggregates.toml").write_text("schema = 1\n")
        (source_dir / "licenses/HaGeZi-GPL-3.0.txt").write_text("Synthetic license fixture only\n")
        candidate_url = "https://raw.githubusercontent.com/v2fly/domain-list-community/master/data/category-cryptocurrency"
        (source_dir / "upstreams.toml").write_text(
            '[v2fly]\nbase_url = "https://raw.githubusercontent.com/v2fly/domain-list-community/master/data"\n'
            '[crypto_candidates]\nurl = "' + candidate_url + '"\n'
            '[sets.AdBlockLite]\nbehavior = "domain"\nparser = "wildcard-domain-list"\nurls = ["' + URL + '"]\n')
        (self.cache / evidence.digest(candidate_url.encode())).write_bytes(b"domain:candidate.fixture.invalid\n")
        for family, required, kind in (("crypto", builder.REQUIRED_CRYPTO_IDS, "exchange"), ("banking", builder.REQUIRED_BANKING_IDS, "bank")):
            entries = []
            for index, identity in enumerate(sorted(required)):
                entries.extend(['[[entities]]', 'id = "' + identity + '"', 'name = "Fixture ' + identity + '"',
                                'kind = "' + kind + '"', 'required = true',
                                'domains = ["suffix:' + identity + '.' + family + '.fixture.invalid"]'])
                if family == "banking":
                    entries.append('region = "' + builder.REGIONS[index % len(builder.REGIONS)] + '"')
            (source_dir / "catalog" / (family + ".toml")).write_text("\n".join(entries) + "\n")

        def run_main(source, cache, baseline, output):
            args = ["build_rules.py", "--output", str(output), "--source-cache", str(cache),
                    "--offline", "--baseline", str(baseline), "--mihomo", str(self.compiler),
                    "--source-commit", "a" * 40]
            # This bypass is deliberately limited to compilation. No fake MRS
            # is produced, and no claim is made that verify_build would pass.
            with patch.object(builder, "SOURCES", source), patch.object(sys, "argv", args), \
                    patch.object(builder, "compile_mrs") as compile_not_run, \
                    patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")), \
                    patch("subprocess.run", side_effect=AssertionError("compiler forbidden")), \
                    contextlib.redirect_stdout(io.StringIO()):
                builder.main()
                self.assertGreater(compile_not_run.call_count, 0)
            self.assertEqual([], list(output.rglob("*.mrs")))
            return {file.relative_to(output).as_posix(): file.read_bytes() for file in output.rglob("*") if file.is_file()}

        bootstrap = self.root / "bootstrap-text"
        original = run_main(source_dir, self.cache, self.baseline, bootstrap)
        self.baseline = bootstrap
        self.candidate = bootstrap
        self.capture()
        first, second = self.root / "first-full-text", self.root / "second-full-text"
        evidence.restore(self.archive, first, self.compiler)
        evidence.restore(self.archive, second, self.compiler)
        outputs = []
        for restored in (first, second):
            outputs.append(run_main(restored / "source/sources", restored / "source-snapshot",
                                    restored / "baseline", restored / "output"))
        self.assertEqual(original, outputs[0])
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(len([name for name in outputs[0] if name.startswith("Surge/")]), 12)
        self.assertIn("Mihomo/AdBlockLite.yaml", outputs[0])
        self.assertIn("SOURCES.json", outputs[0])


if __name__ == "__main__":
    unittest.main()
