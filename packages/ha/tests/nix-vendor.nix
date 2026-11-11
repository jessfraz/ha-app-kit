# Exercise the real importCargoLock crate-only layout with a local source fixture.
# Only fetching is replaced: the unpublished working tree has no Git commit yet.
{pkgs}: let
  root = ../../..;
  kitVersion = (builtins.fromTOML (builtins.readFile (root + /Cargo.toml))).workspace.package.version;
  revision = "1111111111111111111111111111111111111111";
  sourceId = "git+https://github.com/jessfraz/ha-app-kit?tag=v${kitVersion}#${revision}";
  source = pkgs.lib.fileset.toSource {
    inherit root;
    fileset = pkgs.lib.fileset.unions [
      (root + /Cargo.toml)
      (root + /Cargo.lock)
      (root + /packages/ui)
      ../Cargo.toml
      ../brand.py
      ../bundle.py
      ../version-repair.json
      ../icons
      ../rust
      ../ha_app_kit/__init__.py
      ../ha_app_kit/bundle.py
      ../ha_app_kit/versions.py
      ../ha_app_kit/repairs.py
    ];
  };
  lockFile = pkgs.writeText "fictional-companion-Cargo.lock" ''
    version = 4
    [[package]]
    name = "ha-app-kit-ha"
    version = "${kitVersion}"
    source = "${sourceId}"
    [[package]]
    name = "ha-app-ui"
    version = "${kitVersion}"
    source = "${sourceId}"
    [[package]]
    name = "fictional-consumer"
    version = "0.1.0"
    dependencies = ["ha-app-kit-ha", "ha-app-ui"]
  '';
  importLock = pkgs.callPackage (pkgs.path + /pkgs/build-support/rust/import-cargo-lock.nix) {
    fetchgit = _args: source;
  };
  vendor = importLock {
    inherit lockFile;
    outputHashes."ha-app-ui-${kitVersion}" = pkgs.lib.fakeHash;
  };
in
  pkgs.runCommand "ha-app-kit-companion-vendoring" {
    nativeBuildInputs = [
      pkgs.cargo
      (pkgs.python314.withPackages (ps: [ps.pyyaml]))
    ];
  } ''
    export CARGO_HOME="$TMPDIR/cargo-home"
    export CARGO_NET_OFFLINE=true
    mkdir -p "$CARGO_HOME" consumer/src consumer/.cargo companion/translations app
    cat > consumer/Cargo.toml <<'EOF'
    [package]
    name = "fictional-consumer"
    version = "0.1.0"
    edition = "2024"
    [dependencies]
    ha-app-kit-ha = { git = "https://github.com/jessfraz/ha-app-kit", tag = "v${kitVersion}" }
    ha-app-ui = { git = "https://github.com/jessfraz/ha-app-kit", tag = "v${kitVersion}" }
    EOF
    cp ${lockFile} consumer/Cargo.lock
    touch consumer/src/lib.rs
    cp ${vendor}/.cargo/config.toml consumer/.cargo/config.toml
    substituteInPlace consumer/.cargo/config.toml \
      --replace-fail 'directory = "cargo-vendor-dir"' 'directory = "${vendor}"'
    printf '%s\n' '{"domain":"example","version":"1.2.3"}' > companion/manifest.json
    printf '%s\n' '{"issues":{"version_mismatch":{"title":"Fictional mismatch"},"other":{"title":"Keep unrelated","description":"Keep this"}}}' > companion/strings.json
    cp companion/strings.json companion/translations/en.json
    printf '%s\n' '{"title":"Texte conservé"}' > companion/translations/fr.json
    python ${vendor}/ha-app-kit-ha-${kitVersion}/bundle.py \
      --manifest-path "$PWD/consumer/Cargo.toml" \
      --integration "$PWD/companion" > receipt.json
    cmp companion/_app_kit/repairs.py ${vendor}/ha-app-kit-ha-${kitVersion}/ha_app_kit/repairs.py
    printf '%s\n' 'panel_icon: "mdi:mailbox-outline"' > app/config.yaml
    for mode in sync check; do
      python ${vendor}/ha-app-kit-ha-${kitVersion}/brand.py \
        --manifest-path "$PWD/consumer/Cargo.toml" \
        --app "$PWD/app" --integration "$PWD/companion" --"$mode"
    done
    cmp app/icon.png ${vendor}/ha-app-kit-ha-${kitVersion}/icons/png/mailbox-outline/app-icon.png
    cmp companion/brand/icon@2x.png ${vendor}/ha-app-kit-ha-${kitVersion}/icons/png/mailbox-outline/icon@2x.png
    python - <<'PY'
    import json
    import hashlib
    from pathlib import Path
    receipt = json.loads(Path("receipt.json").read_text())
    assert receipt["kit_revision"] == "${revision}"
    assert receipt["kit_tag"] == "v${kitVersion}"
    for path, digest in receipt["translations"].items():
        data = Path("companion", path).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest
        strings = json.loads(data)
        assert strings["issues"]["version_mismatch"]["title"] == "Fictional mismatch"
        assert strings["issues"]["other"]["description"] == "Keep this"
        flow = strings["issues"]["version_mismatch"]["fix_flow"]
        assert flow["step"]["retry"]["submit"] == "Retry version check"
        assert "managed_update_unavailable" in flow["error"]
    assert Path("companion/translations/fr.json").read_text() == '{"title":"Texte conservé"}\n'
    for path in Path("companion/_app_kit").glob("*.py"):
        compile(path.read_text(), str(path), "exec")
    PY
    mkdir "$out"
    cp -R companion/_app_kit "$out/"
    cp companion/strings.json "$out/"
    cp -R companion/translations "$out/"
    cp receipt.json "$out/"
  ''
