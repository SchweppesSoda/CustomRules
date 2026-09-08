# CustomRules

This repository separates reviewed rule sources from generated client artifacts.

## Branch contract

- `master`: catalogs, manual sources, build scripts, workflows, Egern modules,
  Stash overrides, and Sub-Store scripts.
- `auto-build`: generated rules only. Every rule artifact is marked
  `AUTO-GENERATED. DO NOT EDIT.`

Production rule URLs use:

```text
https://raw.githubusercontent.com/SchweppesSoda/CustomRules/refs/heads/auto-build/...
```

Non-rule resources such as `Egern/Modules/` and `Stash/` continue to use
`master`.

## Unified client subscriptions

All ordinary remote rule subscriptions in the maintained ProxyConfig clients
are published here. `sources/consumer-map.json` records the migration from each
old public URL to its generated set and the reason for choosing its source.
MetaCubeX is the preferred domain/IP upstream. Services without an equivalent
MetaCubeX category retain their existing blackmatrix7, dler-io, ACL4SSR or other
reviewed source, explicitly listed in `sources/upstreams.toml`.

`Classical/<Service>` combines the preferred domain set with the former
source's non-domain rules (keywords, IPs, ASN, process, user-agent or URL rules).
Where no equivalent domain set exists, it preserves the whole classical
source. These emit YAML and LIST, plus MRS only when the result is domain-only.
They are not silently reduced to domain-only MRS. Client-specific DNS lists
use domain-only projections. Proxy subscriptions, modules, scripts, icons and
GeoIP/ASN databases remain separately managed.

### Conservative ad blocking

- `AdBlockLite`: the default, reviewed domain-only subset of MetaCubeX
  `category-ads-all`. Its allowlist is `sources/policies/adblock-lite.toml`.
  New upstream entries cannot enter Lite until their full domain values have
  been reviewed. No keyword, IP, broad telemetry, push, shared SDK or login
  rules are included. Smaller coverage is intentional; zero false positives
  is not guaranteed.
- `AdBlock`: the full MetaCubeX category, available as an opt-in replacement.
  Do not stack it with Lite in the same client.
- `HTTPDNS`: the deduplicated domain union of MetaCubeX `httpdns` and
  `category-httpdns-cn`. Clients default to DIRECT and retain an opt-in REJECT
  selection; duplicate hard-blocking plugins/rewrite rules should be disabled.
  Existing saved policy selections may need to be changed on the device.

Both ad variants and HTTPDNS emit `Mihomo/<Name>.yaml/.mrs` and
`Surge/<Name>.list`. All formats are generated from the same selected rules.

### Migration validation

Build and publish artifacts before switching client subscriptions. The
read-only client gate checks URLs, artifact existence and provider behavior:

```text
python scripts/verify_consumers.py --proxyconfig-root ../ProxyConfig --output <verified-build> --include-generated
```

Source provenance and hashes remain in `SOURCES.json`. A fresh per-run
`--source-cache` captures inputs; the second build uses the same cache with
`--offline`. Never reuse an old cache for a new scheduled update. The CI also
verifies the final publication tree and skips copying byte-identical files.

## Sources

- `sources/manual/` contains reviewed classical rule sources such as
  MyDirect, MyProxy, Emby, AirportServers, AirportServersCTC, MyGoHome, and
  TikTok. Every `sources/manual/*.yaml` file is discovered automatically by
  `scripts/build_rules.py` and emits `Mihomo/<name>.yaml` plus
  `Surge/<name>.list`; every manual source always provides these YAML/LIST
  artifacts. MRS output follows the builder's existing eligibility logic.
- `sources/manual/AirportServers.yaml` is the generic airport node-domain
  source. Private provider-sync automation may replace only the text between
  the exact `# BEGIN AUTO-GENERATED PROVIDER DOMAINS` and
  `# END AUTO-GENERATED PROVIDER DOMAINS` markers. Manually protected entries,
  including the OixCloud entries, remain outside that block.
- `sources/manual/AirportServersCTC.yaml` is the CTC-only source. The
  `ctcxianyu.com` and `525536.xyz` suffix rules are protected manual entries;
  any additional CTC provider domains must be emitted inside its marked
  dynamic block. `oss.ctc.lol` is intentionally not pinned and may only be
  supplied dynamically. Both AirportServers sources are DNS-only and accept
  `DOMAIN`/`DOMAIN-SUFFIX` rules; their builder input and generated YAML/LIST
  outputs reject IP-CIDR/IP-CIDR6 and other non-domain rules. IP rules remain
  valid in unrelated classical sources such as `MyDirect.yaml`. The private
  synchronizer emits every live hostname as a `DOMAIN-SUFFIX` for its
  registrable root using an offline Public Suffix List, including public and
  private suffixes; provider-specific allowlists are not required.
- `sources/catalog/crypto.toml` is the entity-level Crypto catalog. Its scope
  is trading accounts, custody, wallets, fiat on/off ramps, and Crypto Cards.
- `sources/catalog/banking.toml` is the entity-level Banking catalog with
  mutually exclusive regions.
- `sources/upstreams.toml` is the only registry for permitted remote sources.
  Every set declares its parser and `domain` or `ipcidr` behavior; the Emby
  declaration also enables the reviewed manual/upstream union.
- `sources/toolchain.toml` pins the Mihomo compiler release and archive
  SHA256.

Large upstream collections are candidate sources only. Unknown components and
unmapped domains are written to
`reports/Crypto-Unmapped-Candidates.txt` on `auto-build`; they are never
promoted automatically.

## Published formats

Crypto and Banking are published in all three formats:

```text
Mihomo/Crypto.yaml
Mihomo/Crypto.mrs
Surge/Crypto.list
Mihomo/Banking.yaml
Mihomo/Banking.mrs
Surge/Banking.list
```

Banking is also published as `Global`, `NorthAmerica`, `Europe`,
`HongKongMacau`, `Singapore`, `JapanKorea`, `MiddleEast`, and `Other`
under `Mihomo/Banking/` and `Surge/Banking/`. The aggregate is validated as
the exact union of the eight regions.

Pure-domain sets also receive MRS output. Classical sets retain their existing
YAML/LIST semantics. Service-domain sets are published at
`Mihomo/<Service>.yaml/.mrs` and `Surge/<Service>.list`; service IP sets use
`Mihomo/IP/<Service>.yaml/.mrs` and `Surge/IP/<Service>.list`. IP YAML/MRS files
use `ipcidr` behavior and LIST files use `IP-CIDR`/`IP-CIDR6` with
`no-resolve`.

The generated `Emby` set is the normalized, de-duplicated literal union of
`sources/manual/Emby.yaml` and V2Fly `category-emby`. Unsupported classical
types found while splitting mixed upstreams are retained for review in
`reports/Unsupported-Upstream-Rules.txt`; they never enter a domain or IP
artifact silently.

## Safety and reproducibility

The `Auto Build Rules` workflow runs for source changes, daily, and manually.
It:

1. downloads the pinned Mihomo release and verifies its archive SHA256;
2. builds into a temporary directory;
3. checks YAML/LIST equality, MRS round trips, region exclusivity, required
   entities, and forbidden broad domains;
4. loads all MRS files through a minimal Mihomo configuration;
5. repeats the build and requires byte-for-byte identical output;
6. blocks a reduction over 5% or total change over 20% against the current
   `auto-build` baseline;
7. publishes only changed files without force-pushing.

The published branch also contains `manifest.json`, `SOURCES.json`,
`SHA256SUMS`, the Crypto candidate-review report, and the unsupported-upstream
report.

Public sources contain domain/rule data only. They must not include provider
subscription URLs, keys, tokens, or node credentials. BitzNet remains an
ordinary dynamic airport entry here; fake-IP/hosts compatibility is handled by
the private configuration TODO rather than this public source.

## Stash and other non-rule resources

- `Stash/Overrides/`: reusable Stash modules.
- `Stash/Scripts/`: scripts used by Stash modules.
- `Stash/Rules/`: Stash-specific supplements.
- `Sub-Store/scripts/stash-provider-transform.js`: provider transformation.
