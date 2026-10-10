#!/usr/bin/env python3
"""Mirror approved public icon packages; never update curated client icons."""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import time
from urllib.parse import quote, unquote, urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import warnings
import xml.etree.ElementTree as ET

from PIL import Image

MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 16_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
REPO_PATTERN = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")


class InvalidAsset(ValueError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def read_json(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def safe_path(root: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if not relative or "\\" in relative or ":" in relative or "\0" in relative or path.is_absolute() or any(p in (".", "..") for p in relative.split("/")):
        raise InvalidAsset("unsafe local path")
    target = root.joinpath(*path.parts)
    resolved_root = root.resolve()
    if not target.resolve().is_relative_to(resolved_root):
        raise InvalidAsset("path outside repository")
    for ancestor in [target, *target.parents]:
        if ancestor == resolved_root.parent:
            break
        if ancestor.is_symlink():
            raise InvalidAsset("symlink in asset path")
    return target


def write_if_changed(path: Path, data: bytes) -> bool:
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)
    return True


def parse_url(url: str) -> dict:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port or parsed.fragment:
        raise InvalidAsset("unapproved URL")
    if parsed.hostname not in ("raw.githubusercontent.com", "github.com"):
        raise InvalidAsset("unapproved host")
    if parsed.query not in ("", "raw=true", "raw=1"):
        raise InvalidAsset("unapproved query")
    raw_parts = parsed.path.lstrip("/").split("/")
    parts = [unquote(p) for p in raw_parts]
    if len(parts) < 4 or any(not p or p in (".", "..") or "/" in p or "\\" in p or "\0" in p for p in parts):
        raise InvalidAsset("unsafe upstream path")
    repo = "/".join(parts[:2])
    if not REPO_PATTERN.fullmatch(repo):
        raise InvalidAsset("invalid repository")
    remainder = parts[2:]
    if parsed.hostname == "github.com":
        if remainder.pop(0) not in ("raw", "blob"):
            raise InvalidAsset("not a GitHub asset URL")
    if remainder[:2] == ["refs", "heads"]:
        remainder = remainder[2:]
    if len(remainder) < 2:
        raise InvalidAsset("missing ref or path")
    return {"repository": repo, "ref": remainder[0], "path": "/".join(remainder[1:])}


def raw_url(repo: str, commit: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{repo}/{commit}/{quote(path, safe='/')}"


def validate_image(data: bytes, suffix: str) -> str:
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise InvalidAsset("image size limit")
    suffix = suffix.lower()
    if suffix in (".png", ".jpg", ".jpeg"):
        # Some upstream .png filenames contain real JPEG images. Keep bytes and
        # use the decoded format as the local extension; curated stays PNG-only.
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            expected = "PNG"
        elif data.startswith(b"\xff\xd8\xff"):
            expected = "JPEG"
        else:
            raise InvalidAsset("invalid raster signature")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            try:
                with Image.open(io.BytesIO(data)) as image:
                    if image.format != expected or image.width * image.height > MAX_PIXELS:
                        raise InvalidAsset("invalid raster image")
                    image.verify()
                with Image.open(io.BytesIO(data)) as image:
                    image.load()
            except Exception as exc:
                raise InvalidAsset("raster decode failed") from exc
        return ".png" if expected == "PNG" else ".jpg"
    if suffix != ".svg":
        raise InvalidAsset("unsupported image format")
    lowered = data.lower()
    if b"<!entity" in lowered:
        raise InvalidAsset("unsafe XML entity")
    declarations = re.findall(br'<!DOCTYPE[^>]*>', data, re.I)
    if b'<!doctype' in lowered and len(declarations) != 1:
        raise InvalidAsset("unsafe XML declaration")
    if declarations:
        match = re.fullmatch(br'''<!DOCTYPE\s+svg\s+PUBLIC\s+["']([^"']+)["']\s+["']([^"']+)["']\s*>''', declarations[0], re.I)
        allowed = {
            (b'-//W3C//DTD SVG 1.1//EN', b'http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd'),
            (b'-//W3C//DTD SVG 1.0//EN', b'http://www.w3.org/TR/2001/REC-SVG-20010904/DTD/svg10.dtd'),
            (b'-//W3C//DTD SVG 20010904//EN', b'http://www.w3.org/TR/2001/REC-SVG-20010904/DTD/svg10.dtd'),
        }
        if not match or match.groups() not in allowed:
            raise InvalidAsset("unapproved SVG doctype")
        # Strip only the validated external declaration for parsing. Never fetch
        # any DTD; original image bytes remain unchanged on disk.
        parse_data = data.replace(declarations[0], b'', 1)
    else:
        parse_data = data
    try:
        tree = ET.fromstring(parse_data)
    except ET.ParseError as exc:
        raise InvalidAsset("invalid SVG") from exc
    if tree.tag.split("}")[-1].lower() != "svg":
        raise InvalidAsset("not an SVG")
    for element in tree.iter():
        if element.tag.split("}")[-1].lower() in ("script", "foreignobject", "iframe", "object", "embed"):
            raise InvalidAsset("active SVG content")
        for name, value in element.attrib.items():
            local = name.split("}")[-1].lower()
            if local.startswith("on"):
                raise InvalidAsset("SVG event handler")
            if local in ("href", "src") and value and not value.startswith("#"):
                raise InvalidAsset("external SVG reference")
            if external_css_reference(value):
                raise InvalidAsset("external SVG style")
        if element.tag.split("}")[-1].lower() == "style" and element.text:
            if "@import" in element.text.lower() or external_css_reference(element.text):
                raise InvalidAsset("external SVG stylesheet")
    return ".svg"


def external_css_reference(value: str) -> bool:
    return any(not match.group(1).strip().strip("'\"").startswith("#") for match in re.finditer(r"url\(([^)]*)\)", value, re.I))


def failure_detail(exc: Exception) -> dict:
    result = {"error": type(exc).__name__}
    if isinstance(exc, InvalidAsset):
        # These messages are fixed strings raised by this module, not upstream bodies.
        result["reason"] = str(exc)
    elif isinstance(exc, HTTPError):
        result["httpStatus"] = exc.code
    return result


class GitHub:
    def __init__(self, seed_cache: Path | None = None):
        self.seed = {}
        if seed_cache:
            index = read_json(seed_cache / "index.json", {})
            for record in index.get("assets", []):
                if record.get("status") == 200 and record.get("path"):
                    path = Path(record["path"])
                    if not path.is_absolute():
                        path = seed_cache / path.name
                    self.seed[record["url"]] = (path, record["sha256"])
        self.commits = {}
        self.trees = {}

    def fetch(self, url: str, maximum=MAX_IMAGE_BYTES) -> bytes:
        parse_url(url)
        if url in self.seed:
            path, expected = self.seed[url]
            data = path.read_bytes()
            if digest(data) != expected:
                raise InvalidAsset("seed cache hash mismatch")
            return data
        last = None
        for attempt in range(3):
            try:
                with urlopen(Request(url, headers={"User-Agent": "ProxyIcons-sync/1"}), timeout=20) as response:
                    parse_url(response.url)
                    data = response.read(maximum + 1)
                    if len(data) > maximum:
                        raise InvalidAsset("download size limit")
                    return data
            except Exception as exc:
                last = exc
                if attempt != 2:
                    time.sleep(0.5 * (attempt + 1))
        raise last

    def api(self, endpoint: str):
        # gh supplies authentication only to the API; no token reaches image hosts.
        result = subprocess.run(["gh", "api", endpoint], check=True, capture_output=True)
        return json.loads(result.stdout)

    def resolve(self, repo: str, ref: str) -> str:
        key = (repo, ref)
        if key not in self.commits:
            commit = ref if SHA_PATTERN.fullmatch(ref) else self.api(f"repos/{repo}/commits/{quote(ref, safe='')}")["sha"]
            if not SHA_PATTERN.fullmatch(commit):
                raise InvalidAsset("invalid resolved commit")
            self.commits[key] = commit
        return self.commits[key]

    def tree(self, repo: str, commit: str):
        key = (repo, commit)
        if key not in self.trees:
            value = self.api(f"repos/{repo}/git/trees/{commit}?recursive=1")
            if value.get("truncated"):
                raise InvalidAsset("truncated upstream tree")
            self.trees[key] = {x["path"]: x["sha"] for x in value["tree"] if x["type"] == "blob"}
        return self.trees[key]


def local_url(config: dict, path: str) -> str:
    return f"https://raw.githubusercontent.com/{config['repository']}/{config['branch']}/{config.get('publishPrefix', '')}{path}"


def relocate_url(config: dict, url: str, allowed_paths: set[str]) -> str:
    """Move retained entries only when they reference a verified local image."""
    prefixes = [local_url(config, ''), *config.get('previousPublishPrefixes', [])]
    for prefix in prefixes:
        if url.startswith(prefix):
            path = url[len(prefix):]
            if path not in allowed_paths:
                raise InvalidAsset('retained collection image is not in local manifests')
            return local_url(config, path)
    raise InvalidAsset('unapproved retained collection URL')


def verify_curated(root: Path) -> dict:
    manifest = read_json(root / "curated.json")
    if not manifest or manifest.get("schema") != 1:
        raise InvalidAsset("missing curated lock")
    names = set()
    aliases = set()
    for record in manifest["icons"]:
        slug = record["slug"]
        if not SLUG_PATTERN.fullmatch(slug) or slug in names or record["path"] != f"icons/{slug}.png":
            raise InvalidAsset("invalid curated identity")
        names.add(slug)
        data = safe_path(root, record["path"]).read_bytes()
        if digest(data) != record["sha256"] or len(data) != record["bytes"] or validate_image(data, ".png") != ".png":
            raise InvalidAsset("curated lock mismatch")
        if not SHA_PATTERN.fullmatch(record.get('origin', {}).get('commit', '')) or git_blob(data) != record.get('gitBlob'):
            raise InvalidAsset("curated Git provenance mismatch")
        for url in record["aliases"]:
            parse_url(url)
            if url in aliases:
                raise InvalidAsset("duplicate curated alias")
            aliases.add(url)
    return manifest


def merge_collection(previous: dict, current: list[dict]) -> list[dict]:
    # Deleted or failed upstream entries keep their last known good local URL.
    result = list(current)
    current_keys = {(x["name"], x["url"]) for x in result}
    for entry in previous.get("icons", []):
        if (entry["name"], entry["url"]) not in current_keys and not any(x["name"] == entry["name"] for x in result):
            result.append(entry)
    return result


def validate_config(config: dict):
    if config.get("schema") != 1 or not REPO_PATTERN.fullmatch(config.get("repository", "")) or config.get("branch") not in ('main', 'master'):
        raise InvalidAsset("invalid sources config")
    prefix = config.get('publishPrefix', '')
    if prefix and (not prefix.endswith('/') or prefix.startswith('/') or not re.fullmatch(r'[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*/', prefix)):
        raise InvalidAsset('unsafe publication prefix')
    previous_prefixes = config.get('previousPublishPrefixes', [])
    if not isinstance(previous_prefixes, list) or len(previous_prefixes) != len(set(previous_prefixes)):
        raise InvalidAsset('invalid previous publication prefixes')
    for previous in previous_prefixes:
        if not previous.endswith('/'):
            raise InvalidAsset('invalid previous publication prefix')
        parse_url(previous + 'icons/example.png')
    identifiers = set()
    for pack in config["packs"]:
        if not SLUG_PATTERN.fullmatch(pack["id"]) or pack["id"] in identifiers or pack["id"] in ("all", "selected"):
            raise InvalidAsset("invalid pack identity")
        identifiers.add(pack["id"])
        parse_url(pack["url"])
        if not pack["assetRepositories"] or any(not REPO_PATTERN.fullmatch(r) for r in pack["assetRepositories"]):
            raise InvalidAsset("invalid asset allowlist")
        for excluded in pack.get("knownUnavailable", []):
            if parse_url(excluded['url'])['repository'] not in pack['assetRepositories'] or not excluded.get('reason'):
                raise InvalidAsset("invalid reviewed exclusion")
        for requested, replacement in pack.get("assetOverrides", {}).items():
            if parse_url(requested)['repository'] not in pack['assetRepositories'] or parse_url(replacement['url'])['repository'] not in pack['assetRepositories'] or not replacement.get('reason'):
                raise InvalidAsset("invalid reviewed historical fallback")


def sync(root: Path, github: GitHub, workers=12) -> dict:
    config = read_json(root / "sources.json")
    validate_config(config)
    curated = verify_curated(root)
    if (root / 'manifest.json').exists():
        verify(root, allow_previous=True, retained_only=True)
    old = read_json(root / "manifest.json", {"schema": 1, "assets": {}, "packages": {}})
    assets = dict(old["assets"])
    packages = dict(old["packages"])
    failures = []
    changed = 0
    changed += relocate_collections(root, config, assets, curated)
    prepared = []
    for pack in config["packs"]:
        try:
            origin = parse_url(pack["url"])
            commit = github.resolve(origin["repository"], origin["ref"])
            data = github.fetch(raw_url(origin["repository"], commit, origin["path"]), MAX_JSON_BYTES)
            payload = json.loads(data)
            if not isinstance(payload, dict) or not isinstance(payload.get("name"), str) or not isinstance(payload.get("icons"), list):
                raise InvalidAsset("invalid icon package")
            entries = []
            exclusions = {r['url'] for r in pack.get('knownUnavailable', [])}
            for entry in payload["icons"]:
                if not isinstance(entry, dict) or not isinstance(entry.get("name"), str) or not entry["name"] or not isinstance(entry.get("url"), str):
                    raise InvalidAsset("invalid package entry")
                icon = parse_url(entry["url"])
                if icon["repository"] not in pack["assetRepositories"]:
                    raise InvalidAsset("asset repository outside allowlist")
                if entry['url'] in exclusions:
                    continue
                override = pack.get('assetOverrides', {}).get(entry['url'])
                entries.append({"name": entry["name"], "url": entry["url"], "origin": parse_url(override['url']) if override else icon, "requestedOrigin": icon})
            prepared.append((pack, payload, {**origin, "commit": commit, "sha256": digest(data)}, entries))
        except Exception as exc:
            failures.append({"package": pack["id"], "stage": "package", **failure_detail(exc)})
    # Resolve repo/ref and trees once, before workers. No API request per image.
    origins = {tuple(x["origin"][k] for k in ("repository", "ref")) for _, _, _, entries in prepared for x in entries}
    resolved = {}
    for repo, ref in sorted(origins):
        try:
            commit = github.resolve(repo, ref)
            resolved[(repo, ref)] = (commit, github.tree(repo, commit))
        except Exception as exc:
            failures.append({"repository": repo, "stage": "resolve", **failure_detail(exc)})
    tasks = {}
    for _, _, _, entries in prepared:
        for entry in entries:
            tasks[entry["url"]] = entry

    def collect(entry):
        url, origin = entry["url"], entry["origin"]
        previous = assets.get(url)
        try:
            commit, tree = resolved[(origin["repository"], origin["ref"])]
            upstream_blob = tree.get(origin["path"])
            if not upstream_blob:
                raise InvalidAsset("asset missing from resolved commit")
            if previous and previous.get("gitBlob") == upstream_blob:
                path = safe_path(root, previous["path"])
                if path.is_file() and digest(path.read_bytes()) == previous["sha256"]:
                    return url, {**previous, "origin": {**origin, "commit": commit}}, None, None
            # Bootstrap cache URLs were branch URLs; compare their Git object to
            # the resolved tree before claiming an immutable origin commit.
            fetched_url = url if url in github.seed else raw_url(origin["repository"], commit, origin["path"])
            data = github.fetch(fetched_url)
            if git_blob(data) != upstream_blob:
                data = github.fetch(raw_url(origin["repository"], commit, origin["path"]))
                if git_blob(data) != upstream_blob:
                    raise InvalidAsset("upstream Git blob mismatch")
            extension = validate_image(data, PurePosixPath(origin["path"]).suffix)
            sha = digest(data)
            record = {"origin": {**origin, "commit": commit}, "gitBlob": upstream_blob, "path": f"library/{sha[:2]}/{sha}{extension}", "sha256": sha, "bytes": len(data)}
            if entry['requestedOrigin'] != origin:
                record['requestedOrigin'] = entry['requestedOrigin']
            return url, record, data, None
        except Exception as exc:
            return url, previous, None, {"url": url, "stage": "image", **failure_detail(exc)}

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for url, record, data, failure in pool.map(collect, tasks.values()):
            if failure:
                failures.append(failure)
            if record:
                assets[url] = record
                if data is not None:
                    changed += write_if_changed(safe_path(root, record["path"]), data)
    for pack, payload, origin, entries in prepared:
        current = [{"name": x["name"], "url": local_url(config, assets[x["url"]]["path"])} for x in entries if x["url"] in assets]
        old_pack = read_json(root / "collections" / f"{pack['id']}.json", {})
        collection = {"name": payload["name"], "description": f"{payload.get('description', '')}\nMirrored by {config['repository']}. Source: {pack['url']}", "icons": merge_collection(old_pack, current)}
        retained = len(collection["icons"]) - len(current)
        if retained:
            failures.append({"package": pack["id"], "stage": "removed", "error": "UpstreamEntryRemoved", "retained": retained})
        if not collection["icons"] and entries:
            failures.append({"package": pack["id"], "stage": "collection", "error": "EmptyCollection"})
            continue
        changed += write_if_changed(root / "collections" / f"{pack['id']}.json", json_bytes(collection))
        packages[pack["id"]] = {"url": pack["url"], "origin": origin, "upstreamCount": len(payload['icons']), "reviewedExclusions": pack.get('knownUnavailable', [])}
    selected = {"name": "CustomRules Icons Selected", "description": "Fixed PNG selections; automatic synchronization never changes these images. See curated.json for provenance and licenses.", "icons": [{"name": x["slug"], "url": local_url(config, x["path"])} for x in curated["icons"]]}
    changed += write_if_changed(root / "collections" / "selected.json", json_bytes(selected))
    all_entries = []
    for pack in config["packs"]:
        collection = read_json(root / "collections" / f"{pack['id']}.json", {})
        all_entries.extend({"name": f"{pack['id']} · {x['name']}", "url": x["url"]} for x in collection.get("icons", []))
    changed += write_if_changed(root / "collections" / "all.json", json_bytes({"name": "CustomRules Icons All", "description": "All mirrored packages. Names are prefixed with their source package; image bytes are deduplicated by SHA256. Licenses differ by source; see ATTRIBUTION.md.", "icons": all_entries}))
    changed += write_if_changed(root / 'aliases.json', json_bytes({'schema': 1, 'icons': {url: local_url(config, record['path']) for record in curated['icons'] for url in record['aliases']}}))
    changed += write_if_changed(root / "manifest.json", json_bytes({"schema": 1, "assets": assets, "packages": packages}))
    # A transient upstream failure is diagnostic, not a new good provenance record.
    report = {"packageCount": len(config["packs"]), "assetReferences": len(assets), "uniqueAssets": len({x['path'] for x in assets.values()}), "changedFiles": changed, "failures": failures}
    verify(root)
    return report


def relocate_collections(root: Path, config: dict, assets: dict, curated: dict) -> int:
    allowed = {record['path'] for record in assets.values()} | {record['path'] for record in curated['icons']}
    updates = []
    for collection_path in sorted((root / 'collections').glob('*.json')):
        collection = read_json(collection_path)
        for entry in collection['icons']:
            entry['url'] = relocate_url(config, entry['url'], allowed)
        collection['name'] = collection['name'].replace('ProxyIcons Selected', 'CustomRules Icons Selected').replace('ProxyIcons All', 'CustomRules Icons All')
        collection['description'] = collection['description'].replace('SchweppesSoda/ProxyIcons', config['repository'])
        updates.append((collection_path, json_bytes(collection)))
    return sum(write_if_changed(path, data) for path, data in updates)


def relocate(root: Path) -> dict:
    """Offline publication move: image/provenance/curated bytes remain fixed."""
    config = read_json(root / 'sources.json')
    validate_config(config)
    curated = verify_curated(root)
    manifest = read_json(root / 'manifest.json')
    verify(root, allow_previous=True)
    changed = relocate_collections(root, config, manifest['assets'], curated)
    changed += write_if_changed(root / 'aliases.json', json_bytes({'schema': 1, 'icons': {url: local_url(config, record['path']) for record in curated['icons'] for url in record['aliases']}}))
    return {**verify(root), 'changedFiles': changed}


def verify(root: Path, allow_previous=False, retained_only=False) -> dict:
    config = read_json(root / "sources.json")
    validate_config(config)
    curated = verify_curated(root)
    manifest = read_json(root / "manifest.json")
    if not manifest or manifest.get("schema") != 1:
        raise InvalidAsset("missing library manifest")
    verified = set()
    checked_data = {}
    for url, record in manifest["assets"].items():
        parse_url(url)
        path = safe_path(root, record["path"])
        if not record["path"].startswith("library/") or not SHA_PATTERN.fullmatch(record["origin"]["commit"]):
            raise InvalidAsset("invalid provenance")
        if record["path"] not in verified:
            data = path.read_bytes()
            extension = validate_image(data, path.suffix)
            if len(data) != record["bytes"] or digest(data) != record["sha256"] or path.name != record["sha256"] + extension:
                raise InvalidAsset("library hash mismatch")
            verified.add(record["path"])
            checked_data[record['path']] = (len(data), digest(data), git_blob(data))
        if checked_data[record['path']] != (record['bytes'], record['sha256'], record['gitBlob']):
            raise InvalidAsset("asset provenance hash mismatch")
    prefix = local_url(config, "")
    package_ids = set(manifest['packages']) if retained_only else {p['id'] for p in config['packs']}
    expected_collections = {f"{pack_id}.json" for pack_id in package_ids} | {"all.json", "selected.json"}
    actual_collections = {p.name for p in (root / "collections").glob("*.json")}
    if actual_collections != expected_collections:
        raise InvalidAsset("generated package set mismatch")
    allowed_paths = verified | {r["path"] for r in curated["icons"]}
    checked_collections = {}
    for collection_path in sorted((root / "collections").glob("*.json")):
        collection = read_json(collection_path)
        if not isinstance(collection.get("name"), str) or not isinstance(collection.get("description"), str):
            raise InvalidAsset("invalid generated package")
        for entry in collection["icons"]:
            if allow_previous:
                entry['url'] = relocate_url(config, entry['url'], allowed_paths)
            if not entry["url"].startswith(prefix):
                raise InvalidAsset("external generated image URL")
            path = entry["url"][len(prefix):]
            if path not in allowed_paths or not safe_path(root, path).is_file():
                raise InvalidAsset("missing generated image")
        checked_collections[collection_path.name] = collection
    selected = checked_collections['selected.json']
    expected_selected = [{"name": x["slug"], "url": local_url(config, x["path"])} for x in curated["icons"]]
    if retained_only:
        # New reviewed selections need not already have generated entries.
        selected_names = [entry['name'] for entry in selected['icons']]
        valid_selected = len(set(selected_names)) == len(selected_names) and all(entry in expected_selected for entry in selected['icons'])
    else:
        valid_selected = selected['icons'] == expected_selected
    if not valid_selected:
        raise InvalidAsset("selected package differs from curated lock")
    expected_all = []
    if retained_only:
        # Check the old aggregate against its own packages, before generating
        # a newly added package or applying an approved source-order change.
        ordered_ids = list(dict.fromkeys(entry['name'].split(' · ', 1)[0] for entry in checked_collections['all.json']['icons']))
        nonempty_ids = {pack_id for pack_id in package_ids if checked_collections[f'{pack_id}.json']['icons']}
        if set(ordered_ids) != nonempty_ids:
            raise InvalidAsset("aggregate package set mismatch")
        ordered_ids.extend(sorted(package_ids - nonempty_ids))
    else:
        ordered_ids = [pack['id'] for pack in config['packs']]
    for pack_id in ordered_ids:
        collection = checked_collections[f"{pack_id}.json"]
        expected_all.extend({"name": f"{pack_id} · {x['name']}", "url": x["url"]} for x in collection['icons'])
    if checked_collections['all.json']["icons"] != expected_all:
        raise InvalidAsset("aggregate package differs from source packages")
    expected_aliases = {url: local_url(config, record['path']) for record in curated['icons'] for url in record['aliases']}
    observed_aliases = read_json(root / 'aliases.json', {}).get('icons', {})
    if allow_previous:
        observed_aliases = {url: relocate_url(config, target, allowed_paths) for url, target in observed_aliases.items()}
    valid_aliases = all(expected_aliases.get(url) == target for url, target in observed_aliases.items()) if retained_only else observed_aliases == expected_aliases
    if not valid_aliases:
        raise InvalidAsset("curated aliases differ from lock")
    licenses = read_json(root / 'licenses/manifest.json')
    if not licenses or licenses.get('schema') != 1:
        raise InvalidAsset("missing license provenance")
    licensed = set(licenses.get('repositoryAliases', {}))
    for record in licenses['sources']:
        licensed.add(record['repository'])
        if not SHA_PATTERN.fullmatch(record['commit']):
            raise InvalidAsset("invalid license commit")
        for document in record['documents']:
            if not document['path'].startswith('licenses/'):
                raise InvalidAsset("invalid license document path")
            data = safe_path(root, document['path']).read_bytes()
            if len(data) != document['bytes'] or digest(data) != document['sha256']:
                raise InvalidAsset("license snapshot hash mismatch")
    origins = {r['origin']['repository'] for r in manifest['assets'].values()} | {r['origin']['repository'] for r in curated['icons']}
    if not origins.issubset(licensed):
        raise InvalidAsset("asset owner lacks license archive")
    return {"curated": len(curated["icons"]), "libraryImages": len(verified), "collections": len(list((root / 'collections').glob('*.json')))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("sync", "check", "relocate"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--seed-cache", type=Path)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = verify(args.root) if args.command == "check" else relocate(args.root) if args.command == 'relocate' else sync(args.root, GitHub(args.seed_cache), args.workers)
    if args.report:
        write_if_changed(args.report, json_bytes(result))
    print(json.dumps({k: len(v) if k == "failures" else v for k, v in result.items()}, sort_keys=True), flush=True)
    return 1 if result.get("failures") else 0


if __name__ == "__main__":
    sys.exit(main())
