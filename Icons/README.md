# CustomRules Icons

Public icon images and Sub-Store icon collections on CustomRules `master`.
This package is independent of rule sources and the `auto-build` branch. The selected PNGs are fixed
copies of reviewed images. The wider library mirrors the 18 icon packages
referenced by Sub-Store frontend 2.34.0.

## Import into Sub-Store

Add a URL below under the frontend's custom icon collections. This setting is
stored in the browser; importing a collection does not change the backend.

- [Selected: 41 fixed PNGs](https://raw.githubusercontent.com/SchweppesSoda/CustomRules/master/Icons/collections/selected.json)
- [All mirrored packages](https://raw.githubusercontent.com/SchweppesSoda/CustomRules/master/Icons/collections/all.json)

The all collection prefixes each icon name with its package identifier. Image
files are deduplicated by SHA256, while each package keeps its own icon names.
Clients can reference a selected image directly, for example
`https://raw.githubusercontent.com/SchweppesSoda/CustomRules/master/Icons/icons/anthropic-white.png`.

| Package | Import URL |
| --- | --- |
| Qure Color | [qure-color.json](https://raw.githubusercontent.com/SchweppesSoda/CustomRules/master/Icons/collections/qure-color.json) |
| Qure Additions | [qure-additions.json](https://raw.githubusercontent.com/SchweppesSoda/CustomRules/master/Icons/collections/qure-additions.json) |
| mini | [mini.json](https://raw.githubusercontent.com/SchweppesSoda/CustomRules/master/Icons/collections/mini.json) |
| mini+ | [mini-plus.json](https://raw.githubusercontent.com/SchweppesSoda/CustomRules/master/Icons/collections/mini-plus.json) |
| mini Color | [mini-color.json](https://raw.githubusercontent.com/SchweppesSoda/CustomRules/master/Icons/collections/mini-color.json) |
| mini Color+ | [mini-color-plus.json](https://raw.githubusercontent.com/SchweppesSoda/CustomRules/master/Icons/collections/mini-color-plus.json) |
| The Magic | [the-magic.json](https://raw.githubusercontent.com/SchweppesSoda/CustomRules/master/Icons/collections/the-magic.json) |
| cc63 | [cc63.json](https://raw.githubusercontent.com/SchweppesSoda/CustomRules/master/Icons/collections/cc63.json) |
| fmz200 | [fmz200.json](https://raw.githubusercontent.com/SchweppesSoda/CustomRules/master/Icons/collections/fmz200.json) |
| 离歌 | [lige.json](https://raw.githubusercontent.com/SchweppesSoda/CustomRules/master/Icons/collections/lige.json) |
| 可莉 | [kelee.json](https://raw.githubusercontent.com/SchweppesSoda/CustomRules/master/Icons/collections/kelee.json) |
| WHATSINStash | [whats-in-stash.json](https://raw.githubusercontent.com/SchweppesSoda/CustomRules/master/Icons/collections/whats-in-stash.json) |
| theSVG default | [thesvg-default.json](https://raw.githubusercontent.com/SchweppesSoda/CustomRules/master/Icons/collections/thesvg-default.json) |
| theSVG dark | [thesvg-dark.json](https://raw.githubusercontent.com/SchweppesSoda/CustomRules/master/Icons/collections/thesvg-dark.json) |
| theSVG light | [thesvg-light.json](https://raw.githubusercontent.com/SchweppesSoda/CustomRules/master/Icons/collections/thesvg-light.json) |
| theSVG color | [thesvg-color.json](https://raw.githubusercontent.com/SchweppesSoda/CustomRules/master/Icons/collections/thesvg-color.json) |
| theSVG azure | [thesvg-azure.json](https://raw.githubusercontent.com/SchweppesSoda/CustomRules/master/Icons/collections/thesvg-azure.json) |
| theSVG gcp | [thesvg-gcp.json](https://raw.githubusercontent.com/SchweppesSoda/CustomRules/master/Icons/collections/thesvg-gcp.json) |

## Synchronization and fixed selections

GitHub Actions checks pull requests without publishing. On Monday at 03:17 UTC,
manual dispatch, and icon source/code/selection changes on master, it validates the
repository and synchronizes the library. Only the synchronization job receives
write permission. Concurrent publications wait for the previous run to finish.

`sources.json` explicitly allows package URLs and their image repositories. A
sync resolves each source ref once, validates downloads against that commit's
Git blob, and verifies PNG/JPEG decoding or safe SVG content. It never executes
upstream scripts. A JPEG stored upstream under a `.png` name retains its exact
bytes and receives a `.jpg` extension in the mirror. Standard W3C SVG external
declarations are parsed without downloading a DTD.

Failed downloads, invalid images, and removed upstream entries keep existing
good images and collection entries. New failures appear in the Actions report
and fail the run; valid updates to other assets can still be committed. Files
are not deleted automatically. An unchanged sync preserves bytes and mtimes.

Two initially broken WHATSINStash links (`icon/discord.png` and
`icon/vercel.png`) have no retrievable original path and are explicitly listed
as `knownUnavailable`; no different artwork is substituted. Its removed
`icon/thebluemosque.png` uses a documented, fixed historical commit. Current package counts and commits are recorded in `manifest.json`;
reviewed exclusions are recorded in `sources.json`.

`curated.json` locks the 41 selected PNGs, their SHA256 hashes, source commits,
and public URL aliases. Automatic synchronization never updates `icons/` or
this lock. The white Anthropic logo and the dollar banknote remain the selected
artwork. `aliases.json` maps previous public icon URLs to these fixed images;
it contains no client configurations or consumer names. To select new artwork,
review its source and license, add a fixed PNG and lock entry, then explicitly
update the client icon URL.

## Local checks

From the `Icons/` directory, install Python 3.12, GitHub CLI, and the pinned dependency:

Authenticate the CLI with `gh auth login`, or provide `GH_TOKEN` for public
GitHub API requests; image downloads never receive that token.

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/sync_icons.py check
python scripts/sync_icons.py sync --report sync-report.json
```

`sources.json` declares the publishing repository, branch and validated `Icons/`
prefix. `python scripts/sync_icons.py relocate` rewrites collections and aliases
offline after an approved publication move, including retained old entries; image
bytes, source provenance and the curated lock remain fixed. Its second run is a
no-op. Only verified local assets and explicitly listed previous prefixes migrate.

Library provenance is in `manifest.json`; selected-image provenance is in
`curated.json`. Original license and README snapshots are in `licenses/`, with
their commits and hashes in `licenses/manifest.json`.

## Attribution and permitted use

Images have different upstream licenses and usage restrictions. The scripts'
MIT license does not relicense third-party images, collection definitions, or
brand marks. See [ATTRIBUTION.md](ATTRIBUTION.md) and the archived original
documents before reusing or redistributing assets. Some sources require
attribution or restrict commercial use. Trademark rights remain with their
respective owners.
