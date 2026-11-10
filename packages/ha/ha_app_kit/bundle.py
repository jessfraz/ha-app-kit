"""Produce a companion's private helper package from a locked Kit checkout."""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .versions import ReleaseVersion

_KIT_URL = "https://github.com/jessfraz/ha-app-kit"
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_RUNTIME_FILES = ("__init__.py", "versions.py", "repairs.py")


@dataclass(frozen=True, slots=True)
class LockedKit:
    root: Path
    revision: str
    tag: str


def _source_identity(value: object) -> tuple[str, str]:
    if not isinstance(value, str) or not value.startswith("git+"):
        raise ValueError("HA App Kit must be a locked Git dependency")
    source = urlsplit(value.removeprefix("git+"))
    if f"{source.scheme}://{source.netloc}{source.path}" != _KIT_URL:
        raise ValueError("Unexpected HA App Kit repository")
    query = parse_qs(source.query, strict_parsing=True)
    if set(query) != {"tag"} or len(query["tag"]) != 1:
        raise ValueError("HA App Kit must use a release tag")
    tag = query["tag"][0]
    if ReleaseVersion.parse(tag).tag != tag or not _SHA.fullmatch(source.fragment):
        raise ValueError("Invalid HA App Kit release identity")
    return source.fragment, tag


def resolve_locked_kit(manifest: Path) -> LockedKit:
    """Use Cargo's supported metadata API, without searching its cache layout."""
    manifest = manifest.resolve(strict=True)
    locked = tomllib.loads(manifest.with_name("Cargo.lock").read_text())
    dependencies = [p for p in locked["package"] if p["name"] == "ha-app-kit-ha"]
    if len(dependencies) != 1:
        raise ValueError("Expected exactly one locked HA App Kit dependency")
    source = dependencies[0].get("source")
    revision, tag = _source_identity(source)
    result = subprocess.run(
        [
            "cargo",
            "metadata",
            "--locked",
            "--format-version",
            "1",
            "--manifest-path",
            str(manifest),
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=manifest.parent,
    )
    metadata = json.loads(result.stdout)
    packages = [
        p
        for p in metadata["packages"]
        if p["name"] == "ha-app-kit-ha" and p["source"] == source
    ]
    if len(packages) != 1:
        raise ValueError("Cargo metadata does not match the locked HA App Kit source")
    package = packages[0]
    if ReleaseVersion.parse(package["version"]) != ReleaseVersion.parse(tag):
        raise ValueError("Locked HA App Kit package version does not match its release")
    crate = Path(package["manifest_path"]).resolve(strict=True).parent
    for name in (*_RUNTIME_FILES, "bundle.py"):
        path = crate / "ha_app_kit" / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Locked HA App Kit companion resources are incomplete")
    return LockedKit(root=crate, revision=revision, tag=tag)


def bundle(kit: LockedKit, integration: Path) -> dict[str, object]:
    """Stage and replace only this producer's unchanged generated package."""
    integration = integration.resolve(strict=True)
    manifest = json.loads((integration / "manifest.json").read_text())
    domain = manifest["domain"]
    if not isinstance(domain, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", domain):
        raise ValueError("Invalid integration domain")
    version = ReleaseVersion.parse(manifest["version"])
    if not _SHA.fullmatch(kit.revision) or ReleaseVersion.parse(kit.tag).tag != kit.tag:
        raise ValueError("Invalid locked Kit identity")
    target = integration / "_app_kit"
    if target.is_symlink():
        raise ValueError("Generated helper package cannot be a symlink")
    marker = target / "source.json"
    if target.exists() and not marker.is_file():
        raise ValueError("Refusing to replace an unowned helper directory")
    if target.exists():
        old = json.loads(marker.read_text())
        if old.get("producer") != "ha-app-kit" or old.get("domain") != domain:
            raise ValueError("Refusing to replace an unowned helper directory")
        expected = {*_RUNTIME_FILES, "version.py", "source.json"}
        for path in target.iterdir():
            if path.name == "__pycache__" and path.is_dir() and not path.is_symlink():
                if all(p.is_file() and p.suffix == ".pyc" for p in path.iterdir()):
                    continue
            if path.name not in expected or not path.is_file() or path.is_symlink():
                raise ValueError("Generated helper package contains unowned files")
        for name in expected - {"source.json"}:
            if hashlib.sha256((target / name).read_bytes()).hexdigest() != old[
                "files"
            ].get(name):
                raise ValueError("Generated helper source was modified")

    files = {
        name: (kit.root / "ha_app_kit" / name).read_bytes() for name in _RUNTIME_FILES
    }
    files["version.py"] = (
        '"""The version of the companion code loaded by this process."""\n\n'
        f'LOADED_VERSION = "{version}"\n'
    ).encode()
    receipt: dict[str, object] = {
        "producer": "ha-app-kit",
        "domain": domain,
        "version": str(version),
        "kit_tag": kit.tag,
        "kit_revision": kit.revision,
        "files": {
            name: hashlib.sha256(data).hexdigest() for name, data in files.items()
        },
    }
    files["source.json"] = (json.dumps(receipt, indent=2) + "\n").encode()
    # Build steps run before importing the companion. A sibling staging tree
    # keeps renames on one filesystem; preserve the old tree if rollback fails.
    staging = Path(tempfile.mkdtemp(prefix=".app-kit-", dir=integration))
    previous = staging / "previous"
    try:
        staged = staging / "_app_kit"
        staged.mkdir()
        for name, data in files.items():
            path = staged / name
            path.write_bytes(data)
            path.chmod(0o644)
        if target.exists():
            target.rename(previous)
            try:
                staged.rename(target)
            except BaseException:
                previous.rename(target)
                raise
            shutil.rmtree(previous)
        else:
            staged.rename(target)
    finally:
        if not previous.exists():
            shutil.rmtree(staging)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-path", type=Path, default=Path("Cargo.toml"))
    parser.add_argument("--integration", type=Path, required=True)
    args = parser.parse_args()
    kit = resolve_locked_kit(args.manifest_path)
    receipt = bundle(kit, args.integration)
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
