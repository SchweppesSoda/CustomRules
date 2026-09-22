# 2026-09-21 Build input evidence

The historical 14.5% AdBlockLite shrink could not be attributed exactly because
that failed run did not retain its fetched inputs. Re-fetching today's mutable
sources would not recreate yesterday's run. This change records future inputs;
it does not claim to recover that missing evidence or approve the shrink.

`SourceRegistry` optionally writes an atomic, fsynced journal after every
successful response, before downstream parsing. Failed requests have no
invented digest. The final published SOURCES file remains unchanged. The
workflow snapshots source/baseline commit identities and packages evidence
after the build step even when it fails. The existing 5% reduction and 20%
total-change gates and explicit `allow_large_change` semantics are unchanged.

The packer accepts only reviewed public GitHub rule repositories, the fixed
GitHub snapshot API and the one existing jsDelivr rule URL; userinfo, query
parameters, fragments and other hosts are rejected. It copies only indexed
cache bodies, approved source files, fixed metadata and baseline LISTs. Each
member is limited to 64 MiB, the total to 256 MiB and membership to 4096 files.
The compiler is not copied into the artifact; it is hashed in chunks under a
separate 256 MiB limit and its actual byte count is recorded. This local work
did not have the fixed Linux binary available to verify its decompressed size.
The later authorized CI must confirm that prerequisite; no compiler is fetched
or executed by the evidence tool. Offline replay requires the operator to hold
the exact separately verified binary, not just this archive.
Baseline lists must exactly match the published manifest's set names/counts.
Hashes of each member, the actual compiler binary, the source toolchain lock
and commit identities accompany the output. No credentials, arbitrary runner
directory, compiler executable or raw log is uploaded. A new legitimate source
outside the whitelist requires a reviewed whitelist change.

The archive action is pinned to
[`actions/upload-artifact` v4.6.2, ea165f8d65b6e75b540449e92b4886f43607fa02](https://github.com/actions/upload-artifact/commit/ea165f8d65b6e75b540449e92b4886f43607fa02).
The dedicated artifact name separates run attempts, retention is 14 days,
and missing evidence is an error. Capture/verification/upload precede publish;
any failure keeps the workflow's normal success gate closed. No permissions
were expanded. Cancellation, runner loss or infrastructure failure can still
prevent archival; those cases must not be reported as recoverable evidence.

Validation: 52 offline Python tests passed, including 14 evidence-specific
tests. Network and subprocess launches were denied, with no attempted denied
operations and no fixture residue. Synthetic success and shrink-failure
archives were restored and replayed twice through the actual Fetcher/parser/
threshold functions with identical bytes and decisions. Parsing failure before
final SOURCES creation, failed fetch with no response, atomic journal failure,
missing/tampered inputs, wrong compiler identity, extra files, capability URLs,
size bounds, incomplete baseline and existing recovery directory preservation
were exercised. This is input and safety-gate validation, not a full Mihomo
compile/round-trip or an actual Actions run. No real upstream source, private
subscription, release or device was accessed.

A further fixture invokes the actual builder `main` using an entirely synthetic
source tree and archived response bodies. Its catalogs satisfy the real required
entity IDs and eight banking regions. Bootstrap and two independent restored
replays produce byte-identical 12 YAML/LIST pairs and text metadata/reports.
Only `compile_mrs` is intercepted; it creates no MRS bytes and invokes no compiler.
Therefore these results establish real text-pipeline replay, not successful MRS
compilation, kernel loading or a complete publishable build.

All 176 URL declarations in current upstreams.toml, eight locally retained
successful SOURCES snapshots (189 or 199 entries each), and the cached
auto-build SOURCES (199 entries) were accepted by the archive whitelist without
new fetching. Cached historical state is compatibility evidence, not a fresh
remote/current-state assertion.

After separate push/CI authorization, require a real build to show an uploaded
artifact, successful offline second build and unchanged publish gates. For a
future incident, preserve the verified artifact before expiration, inspect its
provenance, use the exact reviewed source commit and matching verified compiler,
and replay with `--offline`; missing input remains an explicit limit. The
archived source is not executed by the evidence tool. Source and toolchain
checksums provide consistency, not a signature of origin.

Rollback is a local revert of this feature before publication, or a separately
authorized source revert later. It requires no changes to `auto-build` or
existing published rules and restores the previous lack of failed-input
evidence. Keep any already-retained incident evidence; do not delete recovery
material as part of rollback. No existing retention policy or VM snapshot was
changed.

## 2026-09-22 local application

After explicit authorization, the six-file candidate was applied on the existing master branch with all candidate SHA256 values matching. Only this maintenance note adds the application date. Fresh checks passed: 52 offline tests, no failures/errors/skips or blocked network/process attempts, six local documentation links, three Python syntax checks and seven workflow run blocks checked with bash -n.

The first local test wrapper allowed the wrong scratch scope and was stopped without a valid result. The corrected wrapper allows the two existing isolated fixture roots; production code and tests were unchanged. The valid run completed in 2.13 seconds, including actual main text-pipeline archive replay. Compilation remains mocked: no Linux compiler, MRS round-trip, kernel load or Actions run was performed. This is a local source commit only; no push, rule publication or deployment occurred. Earlier source-whitelist and pinned-action review remains historical evidence.
