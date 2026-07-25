# My Custom Rules

It's designed for `subconverter` transmission.

## Generated Service Rules

`Mihomo/AI.yaml`, `AppleTV.yaml`, `AppleCN.yaml`, and `Apple.yaml` are generated
from MetaCubeX geosite lists. Their matching `Surge/*.list` files are suitable
for Surge, Loon, and Egern. AI combines `category-ai-!cn` with
`apple-intelligence`.

The `Sync Rules` workflow checks upstream daily and can also be run manually.
Generated files should not be edited directly.

## Stash

- `Stash/Overrides/`: reusable Stash modules. PO0-specific modules live in
  [VPS-Toolkit](https://github.com/SchweppesSoda/VPS-Toolkit).
- `Stash/Scripts/`: scripts used by the Stash modules.
- `Stash/Rules/`: Stash-specific classical rule supplements.
- `Sub-Store/scripts/stash-provider-transform.js`: provider transformation
  used by the Stash configuration.
