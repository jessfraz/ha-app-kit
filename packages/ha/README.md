# HA companion

The `ha-app-kit-ha` Cargo resource crate contains the Python repair helper and
its bundler. It is separate from `ha-app-ui`. Cargo and Nix can vendor either
crate without needing a sibling checkout.

Consumers pin the resource crate and UI crate to the same Kit release and commit
in `Cargo.lock`. A packaging step runs the path returned by
`ha_app_kit_ha::bundler_path()` with Python 3.14:

```sh
python /path/to/locked/crate/bundle.py \
  --manifest-path Cargo.toml --integration custom_components/example
```

The producer resolves the resource crate through locked Cargo metadata and
writes only `example/_app_kit`. Its receipt records the Kit tag, exact commit,
companion version, and file hashes. Rebundling refuses unowned or modified
helper files. Home Assistant loads the helper from each integration's private
`_app_kit` package.

For Nix, `cargoLock.allowBuiltinFetchGit = true` supports lock-file updates
without a versioned Kit hash entry. Keep hashes for other dependencies and
verify that both Kit packages have the same expected repository/tag/commit.
`importCargoLock` copies each crate separately; `tests/nix-vendor.nix` exercises
that actual layout and the packaged producer with Cargo offline.

After assigning an entry's runtime data, its coordinator creates one
`VersionRepairs(hass, entry, spec)` and calls `async_start()`. The spec supplies
the public domain, app name, fixed Marketplace repository ID, a backend version
probe, and the Supervisor slug from that entry's native discovery. The slug is
`None` for an externally managed backend. `loaded_version` comes from the
bundled `version.LOADED_VERSION` constant, parsed with `ReleaseVersion.parse`.
Successful coordinator reads call `async_report` with the observed version. The
companion's `repairs.py` returns `create_version_fix_flow(hass, issue_id, spec)`
for this issue.

The native flow first shows the proposed matching release. An explicit menu
selection creates a full Core/database/app/folder backup using the configured
encrypted destinations, verifies every selected copy, installs native updates,
checks both versions, and requests a Core restart when loaded Python differs. It
leaves the issue open until a fresh loaded entry observes parity. A shared HA
lifecycle lock prevents overlapping repairs across separately bundled copies.

Consumers supply their normal issue translations. The fix flow uses `init` menu
options `update_and_restart`, `update_app`, and `restart`, progress action
`updating`, the `RepairReason` abort keys, and `restart_requested`. Its
description placeholders are `app`, `app_version`, `integration_version`, and
`target_version`.

Run the Python checks with `uv run --project packages/ha --frozen` inside the
repository's Nix shell. The tests use native HA entries, registries, services,
and backup models with fictional local I/O. They never update a running HA
installation or contact a household provider.
