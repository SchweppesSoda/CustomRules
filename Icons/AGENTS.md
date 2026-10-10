# CustomRules Icons maintenance

This package is a public icon mirror on CustomRules `master`, under `Icons/`.
It is independent of rule building and must never write `auto-build` or root
rule scripts/tests/dependencies. Its workflow is `../.github/workflows/sync-icons.yml`.
Store only public asset URLs, source metadata,
licenses, and generic icon names. Never import private client/profile/group
inventories, subscriptions, authentication data, or device backups.

`curated.json` and `icons/` are fixed selections. Automatic sync must not modify
them; a human-authorized selection update requires exact byte/hash review.
`sources.json` is the explicit package and asset-repository allowlist.
`scripts/sync_icons.py` owns `library/`, `manifest.json`, `aliases.json`, and `collections/`.
Failed or removed upstream images retain their last known good bytes and URLs.
Do not execute upstream code. Preserve original license and attribution files.

Run `python -m unittest discover -s tests -v` and
`python scripts/sync_icons.py check` for implementation changes. Do not delete
retained artifacts as incidental cleanup. README documents current usage;
routine changes need Git/CI evidence rather than new maintenance reports.
