# unofficial-thesvg-iconset

Unofficial iconset manifests generated from theSVG metadata.

[中文说明](README.zh-CN.md)

Use the iconsets from:

- Release branch: https://github.com/xream/thesvg-iconset/tree/release
- GitHub Releases: https://github.com/xream/thesvg-iconset/releases

Prefer iconset file links from the Release branch when possible.

Each generated JSON file maps one theSVG variant to an iconset, such as
`default.json`, `color.json`, or `mono.json`.

Icons with `collection: "azure"`, `collection: "aws"`, or `collection: "gcp"`
are split into separate collection files instead of the shared variant files:
`azure.json`, `aws.json`, and `gcp.json` for the `default` variant, or
`azure-color.json`, `aws-32.json`, `gcp-mono.json`, etc. for other variants.
This differs from the official theSVG data.

Unlike the official theSVG behavior, `default.json` only includes icons whose
source `variants` contains exactly `default` and no other variants.

See the official theSVG Variants guide before choosing a file:
https://github.com/glincker/thesvg#variants

The generated files contain links to upstream SVG files only. Individual icons
remain subject to their upstream licenses and brand/trademark guidelines.

See [NOTICE.md](NOTICE.md) for license and trademark notes.
