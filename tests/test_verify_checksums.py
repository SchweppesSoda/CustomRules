from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from verify_build import verify_checksums


class ChecksumTests(unittest.TestCase):
    def setUp(self):
        scratch = (ROOT / ".tmp").resolve()
        scratch.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="checksum-test-", dir=scratch)
        self.root = Path(self.temporary.name).resolve()
        assert self.root.is_relative_to(scratch)
        self.addCleanup(self.temporary.cleanup)

    def fixture(self, name="Surge/Test.list", body=b"DOMAIN,example.com\n", digest_body=None):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        digest = hashlib.sha256(body if digest_body is None else digest_body).hexdigest()
        line = f"{digest}  {name}\n"
        (self.root / "SHA256SUMS").write_text(line, encoding="utf-8")
        return line

    def test_exact_bytes_and_text_checkout_normalization(self):
        for name in ("Surge/Test.list", "Mihomo/Test.yaml", "manifest.json",
                     "reports/Test.txt", ".gitattributes"):
            with self.subTest(name=name):
                line = self.fixture(name, b"first\r\nsecond\r\n", b"first\nsecond\n")
                verify_checksums(self.root)
                (self.root / name).unlink()
        self.fixture("Mihomo/Test.mrs", b"binary\r\nbytes")
        verify_checksums(self.root)

    def test_binary_line_endings_are_never_normalized(self):
        for name in ("Mihomo/Test.mrs", "unknown.bin"):
            with self.subTest(name=name):
                self.fixture(name, b"binary\r\nbytes", b"binary\nbytes")
                with self.assertRaisesRegex(RuntimeError, "Checksum mismatch"):
                    verify_checksums(self.root)
                (self.root / name).unlink()

    def test_duplicate_entries_are_rejected_even_when_the_final_hash_matches(self):
        line = self.fixture()
        for prefix in (line, "0" * 64 + "  Surge/Test.list\n"):
            with self.subTest(prefix=prefix[:8]):
                (self.root / "SHA256SUMS").write_text(prefix + line, encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "Duplicate SHA256SUMS"):
                    verify_checksums(self.root)

    def test_malformed_hashes_and_records_have_a_specific_error(self):
        line = self.fixture()
        for invalid in (line.replace("  ", " ", 1), "g" * 64 + "  Surge/Test.list\n",
                        line[1:], "\n" + line):
            with self.subTest(invalid=invalid[:10]):
                (self.root / "SHA256SUMS").write_text(invalid, encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "Malformed SHA256SUMS"):
                    verify_checksums(self.root)

    def test_inventory_and_real_content_changes_still_fail(self):
        self.fixture()
        (self.root / "Surge/Test.list").write_bytes(b"DOMAIN,changed.example\r\n")
        with self.assertRaisesRegex(RuntimeError, "Checksum mismatch"):
            verify_checksums(self.root)
        (self.root / "unexpected.txt").write_text("extra", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "inventory"):
            verify_checksums(self.root)


if __name__ == "__main__":
    unittest.main()
