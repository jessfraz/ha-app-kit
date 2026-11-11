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

The producer resolves the resource crate through locked Cargo metadata, writes
`example/_app_kit`, and merges its shared version-repair translations. Its
receipt records the Kit tag, exact commit, companion version, and file hashes.
Rebundling refuses unowned or modified helper files. Home Assistant loads the
helper from each integration's private `_app_kit` package.

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

The locked producer merges the shared English version-repair `fix_flow` into
`strings.json` and `translations/en.json`. It preserves the issue title, every
unrelated key, and other languages. Both files must already exist. Their
generated hashes are recorded separately from the private helper files in
`source.json`. Temporary preflight failures show their exact translated cause
and a Retry version check button. Retrying refreshes native evidence before
offering the update confirmation. It does not start a backup, update, or
restart. Changed or unavailable entry ownership remains terminal.

Failure logs include only the public integration domain, repair stage, fixed
reason and failed-check codes, and known loaded, backend, and target versions.
They omit entry identifiers, transport exceptions, and backup or provider
details.

Run the Python checks with `uv run --project packages/ha --frozen` inside the
repository's Nix shell. The tests use native HA entries, registries, services,
and backup models with fictional local I/O. They never update a running HA
installation or contact a household provider.

## Native icons

The App's `config.yaml` `panel_icon` selects a pinned Material Design Icons
glyph. Sync the App tile and Marketplace brand from the same locked resource
crate. Run this in the consumer's Home Assistant development environment, which
already provides PyYAML:

```sh
python /path/to/locked/crate/brand.py --sync \
  --app example --integration custom_components/example
```

Commit the generated App `icon.png`, integration `brand/` icons, and both
`ICON-LICENSE.txt` files. Existing logo overrides are synced to the same glyph.
Run the same command with `--check` in CI against the source and again with the
extracted release integration path. A missing or changed file fails the check.
Supervisor reads the tracked App tile and Marketplace reads the packaged brand.
Each companion's `_app_kit` stays limited to runtime Python.

The catalog records the exact upstream source, glyph authors, and SVG checksums.
To regenerate it, run `nix develop -c python scripts/render-icons.py` at the Kit
root. CI renders the catalog from the pinned SVGs and compares the committed PNG
bytes.
