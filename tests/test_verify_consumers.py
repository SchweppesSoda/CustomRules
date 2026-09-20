"""Retired clients must not prevent verification of the remaining consumers."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / "scripts/verify_consumers.py"
spec = importlib.util.spec_from_file_location("verify_consumers", MODULE)
consumer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(consumer)


class ConsumerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.repo = self.root / "profiles"
        self.output = self.root / "artifacts"
        (self.output / "Surge").mkdir(parents=True)
        (self.output / "Surge/Test.list").write_text("DOMAIN,example.test\n")
        (self.output / "manifest.json").write_text(json.dumps({"sets": {
            "Test": {"formats": ["list"]}
        }}))
        url = consumer.BASE + "Surge/Test.list"
        for relative in consumer.CANONICAL + consumer.GENERATED:
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if relative.startswith("Egern/"):
                body = "rules:\n  - domain_set:\n      match: " + url + "\n"
            elif relative.endswith(".yaml"):
                body = "rule-providers:\n  test:\n    url: " + url + "\n"
            else:
                body = "[Remote Rule]\n" + url + ", policy=DIRECT\n"
            path.write_text(body, encoding="utf-8")

    def test_remaining_clients_and_shared_list_pass_without_surge_profiles(self):
        count, failures = consumer.verify(self.repo, self.output, generated=True)
        self.assertEqual([], failures)
        self.assertEqual(10, count)
        self.assertFalse((self.repo / "Surge").exists())

    def test_missing_lite_is_still_an_error(self):
        (self.repo / "Loon/AutoLoonLite.conf").unlink()
        _, failures = consumer.verify(self.repo, self.output)
        self.assertEqual(["Loon/AutoLoonLite.conf: missing profile"], failures)

    def test_generated_checks_remain_opt_in(self):
        (self.repo / "Mihomo/AutoMihomo.OpenWrt-WAN2.yaml").unlink()
        self.assertEqual([], consumer.verify(self.repo, self.output)[1])
        self.assertEqual(["Mihomo/AutoMihomo.OpenWrt-WAN2.yaml: missing profile"],
                         consumer.verify(self.repo, self.output, generated=True)[1])


if __name__ == "__main__":
    unittest.main()
