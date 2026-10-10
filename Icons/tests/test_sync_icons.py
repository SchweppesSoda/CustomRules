import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

SPEC = importlib.util.spec_from_file_location('sync_icons', Path(__file__).resolve().parents[1] / 'scripts/sync_icons.py')
mirror = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mirror)
COMMIT = 'a' * 40
ORIGINAL = 'https://raw.githubusercontent.com/example/art/main/a.png'


def png(color='red'):
    stream = io.BytesIO()
    Image.new('RGBA', (3, 3), color).save(stream, 'PNG')
    return stream.getvalue()


class FakeGitHub:
    def __init__(self):
        self.seed = {}
        self.package = {'name': 'Example', 'description': 'Test', 'icons': [{'name': 'A', 'url': ORIGINAL}]}
        self.data = png()
        self.fail_package = False
        self.fail_image = False

    def resolve(self, repo, ref):
        return COMMIT

    def tree(self, repo, commit):
        return {'a.png': mirror.git_blob(self.data)}

    def fetch(self, url, maximum=mirror.MAX_IMAGE_BYTES):
        if url.endswith('pack.json'):
            if self.fail_package:
                raise OSError('package unavailable')
            return json.dumps(self.package).encode()
        if self.fail_image:
            raise OSError('image unavailable')
        return self.data


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        mirror.write_if_changed(self.root / 'sources.json', mirror.json_bytes({'schema': 1, 'repository': 'example/mirror', 'branch': 'main', 'packs': [{'id': 'example', 'url': 'https://raw.githubusercontent.com/example/art/main/pack.json', 'assetRepositories': ['example/art']}]}))
        data = png('white')
        mirror.write_if_changed(self.root / 'icons/white.png', data)
        original_url = 'https://raw.githubusercontent.com/example/art/main/white.png'
        mirror.write_if_changed(self.root / 'curated.json', mirror.json_bytes({'schema': 1, 'icons': [{'slug': 'white', 'path': 'icons/white.png', 'sha256': mirror.digest(data), 'bytes': len(data), 'gitBlob': mirror.git_blob(data), 'origin': {'repository': 'example/art', 'commit': COMMIT}, 'aliases': [original_url]}]}))
        mirror.write_if_changed(self.root / 'aliases.json', mirror.json_bytes({'schema': 1, 'icons': {original_url: 'https://raw.githubusercontent.com/example/mirror/main/icons/white.png'}}))
        mirror.write_if_changed(self.root / 'licenses/manifest.json', mirror.json_bytes({'schema': 1, 'sources': [{'repository': 'example/art', 'commit': COMMIT, 'documents': []}]}))
        self.github = FakeGitHub()

    def run_sync(self):
        return mirror.sync(self.root, self.github, workers=1)

    def test_full_decode_and_html_rejected(self):
        self.assertEqual(mirror.validate_image(png(), '.png'), '.png')
        with self.assertRaises(mirror.InvalidAsset):
            mirror.validate_image(b'<html>error</html>', '.png')
        with self.assertRaises(mirror.InvalidAsset):
            mirror.validate_image(png()[:20], '.png')

    def test_jpeg_with_png_filename_uses_actual_extension(self):
        data = io.BytesIO()
        Image.new('RGB', (2, 2), 'red').save(data, 'JPEG')
        self.assertEqual(mirror.validate_image(data.getvalue(), '.png'), '.jpg')

    def test_standard_svg_doctype_without_entities_is_allowed(self):
        for identifier, dtd in [('1.1', 'http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd'), ('1.0', 'http://www.w3.org/TR/2001/REC-SVG-20010904/DTD/svg10.dtd'), ('20010904', 'http://www.w3.org/TR/2001/REC-SVG-20010904/DTD/svg10.dtd')]:
            data = f'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG {identifier}//EN" "{dtd}"><svg/>'
            self.assertEqual(mirror.validate_image(data.encode(), '.svg'), '.svg')
        for declaration in ('<!DOCTYPE svg SYSTEM "https://evil.invalid/a">', '<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "https://evil.invalid/svg11.dtd">', '<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd" [<!ENTITY x "evil">]>'):
            with self.assertRaises(mirror.InvalidAsset):
                mirror.validate_image((declaration + '<svg/>').encode(), '.svg')

    def test_upstream_failure_retains_lkg_bytes_and_collection(self):
        self.run_sync()
        manifest_before = (self.root / 'manifest.json').read_bytes()
        collection_before = (self.root / 'collections/example.json').read_bytes()
        self.github.data = b'<html>404</html>'
        result = self.run_sync()
        self.assertEqual(len(result['failures']), 1)
        self.assertEqual((self.root / 'manifest.json').read_bytes(), manifest_before)
        self.assertEqual((self.root / 'collections/example.json').read_bytes(), collection_before)
        self.github.fail_package = True
        self.run_sync()
        self.assertEqual((self.root / 'collections/example.json').read_bytes(), collection_before)

    def test_upstream_deletion_retains_previous_entry(self):
        self.run_sync()
        before = mirror.read_json(self.root / 'collections/example.json')['icons']
        self.github.package['icons'] = []
        self.run_sync()
        self.assertEqual(mirror.read_json(self.root / 'collections/example.json')['icons'], before)
        self.assertEqual(len(mirror.read_json(self.root / 'manifest.json')['assets']), 1)

    def test_no_op_preserves_all_output_bytes_and_mtime(self):
        self.run_sync()
        before = {p.relative_to(self.root): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}
        result = self.run_sync()
        self.assertEqual(result['changedFiles'], 0)
        after = {p.relative_to(self.root): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(after, before)

    def test_sync_generates_newly_added_package_from_valid_existing_library(self):
        self.run_sync()
        config = mirror.read_json(self.root / 'sources.json')
        config['packs'].append({**config['packs'][0], 'id': 'second'})
        mirror.write_if_changed(self.root / 'sources.json', mirror.json_bytes(config))
        with self.assertRaises(mirror.InvalidAsset):
            mirror.verify(self.root)
        self.assertEqual(self.run_sync()['failures'], [])
        self.assertEqual(mirror.verify(self.root)['collections'], 4)
        self.assertEqual(len(mirror.read_json(self.root / 'collections/all.json')['icons']), 2)

    def test_valid_empty_package_can_sync_twice(self):
        self.github.package['icons'] = []
        self.assertEqual(self.run_sync()['failures'], [])
        self.assertEqual(mirror.verify(self.root)['collections'], 3)
        self.assertEqual(mirror.read_json(self.root / 'collections/all.json')['icons'], [])
        second = self.run_sync()
        self.assertEqual(second['failures'], [])
        self.assertEqual(second['changedFiles'], 0)

    def test_sync_generates_new_reviewed_selection_without_changing_images(self):
        self.run_sync()
        curated = mirror.read_json(self.root / 'curated.json')
        data = png('blue')
        mirror.write_if_changed(self.root / 'icons/blue.png', data)
        curated['icons'].append({**curated['icons'][0], 'slug': 'blue', 'path': 'icons/blue.png', 'sha256': mirror.digest(data), 'bytes': len(data), 'gitBlob': mirror.git_blob(data), 'aliases': ['https://raw.githubusercontent.com/example/art/main/blue.png']})
        mirror.write_if_changed(self.root / 'curated.json', mirror.json_bytes(curated))
        self.assertEqual(self.run_sync()['failures'], [])
        self.assertEqual(mirror.verify(self.root)['curated'], 2)
        self.assertEqual((self.root / 'icons/blue.png').read_bytes(), data)

    def test_curated_never_changes_and_lock_failure_stops_writes(self):
        self.run_sync()
        selected = (self.root / 'icons/white.png').read_bytes()
        lock = (self.root / 'curated.json').read_bytes()
        self.github.data = png('blue')
        self.run_sync()
        self.assertEqual((self.root / 'icons/white.png').read_bytes(), selected)
        self.assertEqual((self.root / 'curated.json').read_bytes(), lock)
        before = (self.root / 'manifest.json').read_bytes()
        (self.root / 'icons/white.png').write_bytes(png('black'))
        with self.assertRaises(mirror.InvalidAsset):
            self.run_sync()
        self.assertEqual((self.root / 'manifest.json').read_bytes(), before)

    def test_packages_rewrite_all_images_and_content_deduplicates(self):
        self.github.package['icons'].append({'name': 'Same bytes', 'url': 'https://github.com/example/art/blob/main/a.png?raw=true'})
        self.run_sync()
        result = mirror.verify(self.root)
        self.assertEqual(result['libraryImages'], 1)
        for path in (self.root / 'collections').glob('*.json'):
            for entry in mirror.read_json(path)['icons']:
                self.assertTrue(entry['url'].startswith('https://raw.githubusercontent.com/example/mirror/main/'))
        self.assertEqual(len(mirror.read_json(self.root / 'collections/all.json')['icons']), 2)

    def test_malicious_paths_and_unapproved_hosts_rejected(self):
        for path in ('../escape.png', 'library/../../escape', '/tmp/escape', 'library\\escape', 'C:/escape', 'library/./file'):
            with self.subTest(path=path), self.assertRaises(mirror.InvalidAsset):
                mirror.safe_path(self.root, path)
        for url in ('https://example.org/a.png', 'https://raw.githubusercontent.com/a/b/main/../a.png', 'https://raw.githubusercontent.com/a/b/main/%2e%2e/a.png', 'https://raw.githubusercontent.com/a/b/main/a%2fb.png', 'https://user:pass@github.com/a/b/raw/main/a.png'):
            with self.subTest(url=url), self.assertRaises(mirror.InvalidAsset):
                mirror.parse_url(url)

    def test_svg_active_content_and_external_references_rejected(self):
        self.assertEqual(mirror.validate_image(b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>', '.svg'), '.svg')
        for data in (b'<svg><script>alert(1)</script></svg>', b'<svg onload="x"/>', b'<svg><image href="https://evil.invalid/a.png"/></svg>', b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg/>', b'<svg><style>@import "https://evil.invalid/";</style></svg>'):
            with self.subTest(data=data), self.assertRaises(mirror.InvalidAsset):
                mirror.validate_image(data, '.svg')

    def test_svg_internal_css_references_allow_quotes_and_whitespace(self):
        for reference in ('url(#gradient)', 'url("#gradient")', "url('#gradient')", 'url( #gradient )', 'url( "#gradient" )'):
            data = f'<svg><path fill=\'{reference}\'/></svg>'.replace("fill='url('#gradient')'", 'fill="url(\'#gradient\')"').replace('fill=\'url("#gradient")\'', 'fill=\'url(&quot;#gradient&quot;)\'').replace('fill=\'url( "#gradient" )\'', 'fill=\'url( &quot;#gradient&quot; )\'').encode()
            with self.subTest(reference=reference):
                self.assertEqual(mirror.validate_image(data, '.svg'), '.svg')
        for reference in ('url(https://evil.invalid/a)', 'url("https://evil.invalid/a")', 'url( data:text/html,test )'):
            with self.subTest(reference=reference):
                self.assertTrue(mirror.external_css_reference(reference))

    def test_check_requires_complete_packages_and_exact_aggregate(self):
        self.run_sync()
        aggregate = self.root / 'collections/all.json'
        original = aggregate.read_bytes()
        aggregate.unlink()
        with self.assertRaises(mirror.InvalidAsset):
            mirror.verify(self.root)
        aggregate.write_bytes(original)
        data = mirror.read_json(aggregate)
        data['icons'] = []
        mirror.write_if_changed(aggregate, mirror.json_bytes(data))
        with self.assertRaises(mirror.InvalidAsset):
            mirror.verify(self.root)

    def test_check_rejects_untracked_orphan_image_reference(self):
        self.run_sync()
        orphan = png('green')
        mirror.write_if_changed(self.root / 'library/orphan.png', orphan)
        collection = mirror.read_json(self.root / 'collections/example.json')
        collection['icons'][0]['url'] = 'https://raw.githubusercontent.com/example/mirror/main/library/orphan.png'
        mirror.write_if_changed(self.root / 'collections/example.json', mirror.json_bytes(collection))
        with self.assertRaises(mirror.InvalidAsset):
            mirror.verify(self.root)

    def test_initial_failed_package_cannot_check_green(self):
        self.github.fail_package = True
        with self.assertRaises(mirror.InvalidAsset):
            self.run_sync()

    def test_allowlist_violation_retains_previous_package(self):
        self.run_sync()
        before = (self.root / 'collections/example.json').read_bytes()
        self.github.package['icons'] = [{'name': 'Other', 'url': 'https://raw.githubusercontent.com/not/approved/main/x.png'}]
        result = self.run_sync()
        self.assertTrue(result['failures'])
        self.assertEqual((self.root / 'collections/example.json').read_bytes(), before)

    def migrate_config(self):
        config = mirror.read_json(self.root / 'sources.json')
        config.update(repository='example/rules', branch='master', publishPrefix='Icons/', previousPublishPrefixes=['https://raw.githubusercontent.com/example/mirror/main/'])
        mirror.write_if_changed(self.root / 'sources.json', mirror.json_bytes(config))

    def test_prefix_migration_preserves_images_and_removed_lkg_entries(self):
        self.run_sync()
        images = {p.relative_to(self.root): (p.read_bytes(), p.stat().st_mtime_ns) for directory in ('icons', 'library') for p in (self.root / directory).rglob('*') if p.is_file()}
        original_lock = (self.root / 'curated.json').read_bytes()
        self.migrate_config()
        result = mirror.relocate(self.root)
        self.assertEqual(result['collections'], 3)
        self.github.package['icons'] = []
        self.run_sync()
        current = mirror.read_json(self.root / 'collections/example.json')['icons']
        self.assertEqual(len(current), 1)
        self.assertTrue(current[0]['url'].startswith('https://raw.githubusercontent.com/example/rules/master/Icons/library/'))
        self.assertEqual((self.root / 'curated.json').read_bytes(), original_lock)
        for relative, (content, mtime) in images.items():
            self.assertEqual((self.root / relative).read_bytes(), content)
            self.assertEqual((self.root / relative).stat().st_mtime_ns, mtime)

    def test_failed_package_after_move_keeps_only_new_local_urls(self):
        self.run_sync()
        self.migrate_config()
        self.github.fail_package = True
        result = self.run_sync()
        self.assertTrue(result['failures'])
        self.assertEqual(mirror.verify(self.root)['collections'], 3)
        for path in (self.root / 'collections').glob('*.json'):
            for entry in mirror.read_json(path)['icons']:
                self.assertTrue(entry['url'].startswith('https://raw.githubusercontent.com/example/rules/master/Icons/'))

    def test_offline_relocation_is_noop_after_first_move(self):
        self.run_sync()
        self.migrate_config()
        mirror.relocate(self.root)
        before = {p.relative_to(self.root): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(mirror.relocate(self.root)['changedFiles'], 0)
        after = {p.relative_to(self.root): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_invalid_publish_prefix_and_retained_url_fail_closed(self):
        self.run_sync()
        config = mirror.read_json(self.root / 'sources.json')
        for prefix in ('../Icons/', '/Icons/', 'Icons/../../', 'Icons\\', 'https://evil.invalid/'):
            with self.subTest(prefix=prefix), self.assertRaises(mirror.InvalidAsset):
                mirror.validate_config({**config, 'publishPrefix': prefix})
        self.migrate_config()
        path = self.root / 'collections/example.json'
        collection = mirror.read_json(path)
        collection['icons'][0]['url'] = 'https://raw.githubusercontent.com/example/mirror/main/library/untracked.png'
        mirror.write_if_changed(path, mirror.json_bytes(collection))
        before = {p.name: p.read_bytes() for p in (self.root / 'collections').glob('*.json')}
        with self.assertRaises(mirror.InvalidAsset):
            mirror.relocate(self.root)
        self.assertEqual(before, {p.name: p.read_bytes() for p in (self.root / 'collections').glob('*.json')})

    def test_late_bad_collection_or_image_hash_writes_nothing_on_move(self):
        self.run_sync()
        self.migrate_config()
        selected_path = self.root / 'collections/selected.json'
        selected = mirror.read_json(selected_path)
        selected['icons'][0]['url'] = 'https://raw.githubusercontent.com/unapproved/other/main/icons/white.png'
        original_selected = selected_path.read_bytes()
        mirror.write_if_changed(selected_path, mirror.json_bytes(selected))
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with self.assertRaises(mirror.InvalidAsset):
            mirror.relocate(self.root)
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        selected_path.write_bytes(original_selected)
        asset = next((self.root / 'library').rglob('*.png'))
        asset.write_bytes(png('blue'))
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with self.assertRaises(mirror.InvalidAsset):
            mirror.relocate(self.root)
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})


if __name__ == '__main__':
    unittest.main()
