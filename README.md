# CustomRules

This repository separates reviewed rule sources from generated client artifacts.

## Branch contract

- `master`: catalogs, manual sources, build scripts, workflows, Egern modules,
  Stash overrides, Sub-Store scripts, and [icon assets/collections](Icons/README.md).
- `auto-build`: generated rules only. Every rule artifact is marked
  `AUTO-GENERATED. DO NOT EDIT.`

Production rule URLs use:

```text
https://raw.githubusercontent.com/SchweppesSoda/CustomRules/refs/heads/auto-build/...
```

Non-rule resources such as `Egern/Modules/`, `Stash/` and `Icons/` continue to use
`master`.

## Icons

`Icons/` contains fixed PNG selections, mirrored Sub-Store collections, source
provenance and original licenses. Use the [selected collection](https://raw.githubusercontent.com/SchweppesSoda/CustomRules/master/Icons/collections/selected.json)
or [all packages](https://raw.githubusercontent.com/SchweppesSoda/CustomRules/master/Icons/collections/all.json).
Weekly/manual icon sync has its own [workflow](.github/workflows/sync-icons.yml),
tests and dependency file under `Icons/`; it never builds rules or changes
`auto-build`. Automatic library updates keep selected artwork fixed. See the
[icon guide](Icons/README.md) for direct image URLs and source usage restrictions.

## Unified client subscriptions

Reviewed sources produce shared domain, IP and classical sets for Mihomo,
Stash and Egern. The [rule guide](docs/rule-sources.md#unified-client-subscriptions)
describes source selection and client-specific semantics.

### Shared China coverage

[China coverage](docs/rule-sources.md#shared-china-coverage) combines the pinned
MetaCubeX snapshot with reviewed supplements and exclusions.

### Conservative ad blocking

[AdBlockLite, AdBlock and HTTPDNS](docs/rule-sources.md#conservative-ad-blocking)
have distinct sources and routing requirements; they are not interchangeable.

### Migration validation

[Validate consumers](docs/rule-sources.md#migration-validation) against verified
artifacts before changing subscriptions. Retired clients stay outside active discovery.

### Claude supplemental routing

[Claude supplements](docs/rule-sources.md#claude-supplemental-routing) cover
optional telemetry and ASN routing without changing exit selection.

## Policy aggregates

[Policy aggregates](docs/rule-sources.md#policy-aggregates) preserve the exact
member union and each client's rule conditions.

## Egern rule partitions

[Egern partitions](docs/rule-sources.md#egern-rule-partitions) preserve source
order while separating domestic and overseas policy coverage.

## Sources

[Source ownership](docs/rule-sources.md#sources) covers manual rules, catalogs,
upstream declarations, generated airport markers and the pinned compiler.

## Published formats

The [format guide](docs/rule-sources.md#published-formats) documents stable
YAML, MRS and LIST paths, behavior and compatibility exceptions.

## Safety and reproducibility

[Build and validation](docs/build-and-validation.md) explains the workflow's
validation gates, reproducibility checks and bounded build evidence.

## Stash and other non-rule resources

- [Egern 网络诊断雷达](Egern/Modules/README.md): native widgets combining local/exit IP information, ASN, IPPure risk and service probes, with medium/large layouts and scoped local caching.
- [Stash Network Radar](Stash/Overrides/NetworkRadar.stoverride) adds two homepage exit cards with independent seven-sample HTTP histories. Tap a card for local network details, ASN, IPPure risk, or a fresh measurement. Nine third-party service cards show their configured policy’s observed exit and service response. In standalone profiles, set `proxyPolicy` and any `servicePolicies` overrides in the shared `radar-settings` argument to match local group names.
- `Stash/Overrides/`: reusable Stash modules.
- `Stash/Scripts/`: scripts used by Stash modules.
- `Stash/Rules/`: Stash-specific supplements.
- `Sub-Store/scripts/stash-provider-transform.js`: provider transformation.

## Maintenance entry points

[AGENTS.md](./AGENTS.md) records the `master` / `auto-build` exception, checkout ownership, validation and commit rules. [.github/workflows/sync-rules.yml](./.github/workflows/sync-rules.yml) owns generated publication; [scripts/verify_consumers.py](./scripts/verify_consumers.py) checks downstream subscription paths and behavior.

PO0 official reporting modules belong to [VPS-Toolkit](https://github.com/SchweppesSoda/VPS-Toolkit/tree/main/scripts/po0/nftables/clients), and reusable maintenance workflows belong to [proxy-vps-skills](https://github.com/SchweppesSoda/proxy-vps-skills). Private client configuration and device recovery records remain outside this public repository.

Use ignored `.tmp/` for disposable checks and `.build/` for build/tool caches.
Before cleanup, distinguish disposable output from unique recovery evidence;
see [temporary files and build evidence](docs/build-and-validation.md#temporary-files-and-build-evidence).
