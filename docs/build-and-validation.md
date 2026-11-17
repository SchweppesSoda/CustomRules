# Build, validation and evidence

[Repository overview](../README.md) · [Sources and client formats](rule-sources.md)

Run commands from the repository root. The [rule workflow](../.github/workflows/sync-rules.yml)
owns `auto-build`; the [consumer gate](../scripts/verify_consumers.py) checks
downstream subscription paths and behavior. See [migration validation](rule-sources.md#migration-validation)
for client discovery and offline reproduction. Icon checks use the separate [icon guide](../Icons/README.md#local-checks).

## Safety and reproducibility

The `Auto Build Rules` workflow runs for source changes, daily, and manually.
It uses the job's GitHub token to resolve the MetaCubeX snapshot commit.
The token is scoped to that API request. Rule downloads remain public.

It:

1. downloads the pinned Mihomo release and verifies its archive SHA256;
2. builds into a temporary directory;
3. checks YAML/LIST equality, MRS round trips, region exclusivity, required
   entities, and forbidden broad domains;
4. loads all MRS files through a minimal Mihomo configuration;
5. repeats the build and requires byte-for-byte identical output;
6. reports changes against the current `auto-build` baseline, emitting advisory
   warnings for shrinkage over 5% or total changes over 20%; percentages do not
   block publication;
7. publishes only changed files without force-pushing.

`reports/Rule-Changes.json` records counts, complete added/removed rules,
whole-set additions/removals, and removed domain rules still covered by a current
suffix. This coverage analysis does not infer equivalence for IP, wildcard,
process or cross-set routing. `reports/Rule-Changes.md` summarizes changed sets
in the Actions job summary. Reports are checksummed and preserved in build evidence.
No percentage exception or manual override is needed for small sets or airports.

Download/parse failures, unexpectedly empty sources or non-partition outputs,
required entities, forbidden broad domains, exact aggregate/partition membership,
MRS compilation/loading and reproducibility failures still block the entire
publication. Declared partitions may legitimately be empty. The legacy builder
`--allow-large-change` option remains accepted for saved commands, but is a no-op:
it suppresses neither validation nor change notices. The workflow has no override input.

The published branch also contains `manifest.json`, `SOURCES.json`,
`SHA256SUMS`, the Crypto candidate-review report, and the unsupported-upstream
report. Checksum entries must be unique and well-formed. Windows checkout
line-ending normalization is accepted only for generated text; MRS and other
binary artifacts require an exact byte checksum.

Public sources contain domain/rule data only. They must not include provider
subscription URLs, keys, tokens, or node credentials. BitzNet remains an
ordinary dynamic airport entry here; fake-IP/hosts compatibility is handled by
the private configuration repository’s Provider Compatibility writer rather than this public source.

## Temporary files and build evidence

Use `.tmp/` for local validation output and `.build/` for build/tool caches. Preserve source snapshots needed for reproducing a past run outside the repository before cleanup; a new scheduled update must obtain a fresh source cache.

The build workflow preserves a bounded `public-build-evidence-<run>-<attempt>`
Actions artifact on both successful builds and build failures, for
14 days. It contains public source responses journaled before parsing, their
hashes, source and baseline commit identities, reviewed builder/source files,
the complete baseline LIST inventory and counts, baseline/current source
metadata and change reports when available, and the compiler's actual binary hash plus pinned
version/archive hash. It excludes credentials, arbitrary cache files, raw logs
and compiler binaries. Evidence creation or upload failure blocks publication.
The historical `allow_large_change` evidence field remains readable for older runs;
new runs do not use it to bypass checks.

`scripts/build_evidence.py verify <artifact-directory>` checks the file
inventory, hashes, public-source whitelist, size limits and baseline counts.
`restore <artifact-directory> <new-directory> --compiler <verified-mihomo>`
additionally requires the exact recorded compiler hash, then copies verified
inputs to a new directory. Neither command fetches sources or executes a
compiler/archived script. Inspect artifact provenance and compare its
`source_commit` and archived source hashes with the reviewed source checkout
before executing a replay; internal checksums alone do not establish trust.
Use that checkout's builder with restored `source-snapshot`, restored
`baseline`, the recorded source commit/allow flag, a new output and `--offline`.
A parsing/fetch failure can leave only a partial input snapshot; the offline
builder must reject any later missing input rather than fetch a replacement.

This artifact is short-term build evidence, not a long-term backup or a
guarantee that a full build can finish. Retain selected incident evidence
separately before expiration.
