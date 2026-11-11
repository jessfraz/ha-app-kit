"""The real Cargo producer and vendored Cargo metadata feed private companions."""

import asyncio
import hashlib
import importlib
import json
import os
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant.common import MockModule, mock_integration

from ha_app_kit.bundle import LockedKit, bundle, resolve_locked_kit

ROOT = Path(__file__).parents[3]
KIT_VERSION = tomllib.loads((ROOT / "Cargo.toml").read_text())["workspace"]["package"][
    "version"
]
SOURCE = f"git+https://github.com/jessfraz/ha-app-kit?tag=v{KIT_VERSION}#" + "1" * 40


@pytest.fixture(scope="module")
def resource_crate(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("cargo-package")
    subprocess.run(
        [
            "cargo",
            "package",
            "--locked",
            "--offline",
            "--no-verify",
            "--allow-dirty",
            "--package",
            "ha-app-kit-ha",
            "--target-dir",
            str(directory / "target"),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    archive = directory / f"target/package/ha-app-kit-ha-{KIT_VERSION}.crate"
    with tarfile.open(archive) as reader:
        reader.extractall(directory / "unpacked", filter="data")
    return directory / f"unpacked/ha-app-kit-ha-{KIT_VERSION}"


def consumer(directory: Path, crate: Path) -> Path:
    directory.mkdir()
    (directory / "src").mkdir()
    (directory / "src/lib.rs").write_text("// Fictional build-time consumer.\n")
    manifest = directory / "Cargo.toml"
    manifest.write_text(
        f"""[package]
name = "fictional-consumer"
version = "0.1.0"
edition = "2024"

[dependencies.ha-app-kit-ha]
git = "https://github.com/jessfraz/ha-app-kit"
tag = "v{KIT_VERSION}"
"""
    )
    (directory / "Cargo.lock").write_text(
        f'''version = 4
[[package]]
name = "ha-app-kit-ha"
version = "{KIT_VERSION}"
source = "{SOURCE}"
[[package]]
name = "fictional-consumer"
version = "0.1.0"
dependencies = ["ha-app-kit-ha"]
'''
    )
    # This is Cargo's actual directory source interface used by importCargoLock.
    (crate / ".cargo-checksum.json").write_text('{"files":{},"package":null}')
    (directory / ".cargo").mkdir()
    (directory / ".cargo/config.toml").write_text(
        f'''[source."{SOURCE}"]
git = "https://github.com/jessfraz/ha-app-kit"
tag = "v{KIT_VERSION}"
replace-with = "vendored-kit"
[source.vendored-kit]
directory = {json.dumps(str(crate.parent))}
'''
    )
    return manifest


def integration(path: Path, domain: str) -> Path:
    path.mkdir()
    (path / "__init__.py").write_text('"""Fictional companion."""\n')
    (path / "manifest.json").write_text(
        json.dumps({"domain": domain, "version": "1.2.3"})
    )
    strings = {
        "config": {"step": {"user": {"title": "Keep fictional setup"}}},
        "issues": {
            "version_mismatch": {
                "title": "Keep fictional mismatch",
                "short_title": "Keep short title",
                "fix_flow": {"abort": {"old_key": "Obsolete shared flow"}},
            },
            "other_issue": {
                "title": "Keep unrelated issue",
                "description": "Keep unrelated description",
            },
        },
    }
    (path / "strings.json").write_text(json.dumps(strings))
    (path / "translations").mkdir()
    (path / "translations/en.json").write_text(json.dumps(strings))
    (path / "translations/fr.json").write_text('{"title":"Texte conservé"}\n')
    return path


def test_real_vendored_cargo_metadata_and_packaged_producer(
    resource_crate: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CARGO_NET_OFFLINE", "true")
    manifest = consumer(tmp_path / "consumer", resource_crate)
    kit = resolve_locked_kit(manifest)
    assert kit.root == resource_crate
    assert kit.revision == "1" * 40 and kit.tag == f"v{KIT_VERSION}"
    target = integration(tmp_path / "example", "example")
    result = subprocess.run(
        [
            "python",
            str(kit.root / "bundle.py"),
            "--manifest-path",
            str(manifest),
            "--integration",
            str(target),
        ],
        env=os.environ.copy(),
        check=True,
        capture_output=True,
        text=True,
    )
    receipt = json.loads(result.stdout)
    assert receipt["kit_revision"] == kit.revision
    for relative, digest in receipt["translations"].items():
        assert hashlib.sha256((target / relative).read_bytes()).hexdigest() == digest
    assert (target / "_app_kit/repairs.py").read_bytes() == (
        resource_crate / "ha_app_kit/repairs.py"
    ).read_bytes()
    assert (
        (target / "_app_kit/version.py")
        .read_text()
        .endswith('LOADED_VERSION = "1.2.3"\n')
    )
    # A caller's manual helper edit is never silently overwritten on rebundle.
    (target / "_app_kit/versions.py").write_text("# Preserve unexpected source work.\n")
    with pytest.raises(ValueError, match="modified"):
        bundle(kit, target)
    assert (
        target / "_app_kit/versions.py"
    ).read_text() == "# Preserve unexpected source work.\n"


async def test_packaged_producer_exposes_native_repair_translations_only(
    resource_crate: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hass: HomeAssistant,
) -> None:
    monkeypatch.setenv("CARGO_NET_OFFLINE", "true")
    manifest = consumer(tmp_path / "consumer", resource_crate)
    target = integration(tmp_path / "example", "example")
    originals = {
        relative: (target / relative).read_bytes()
        for relative in ("strings.json", "translations/en.json", "translations/fr.json")
    }
    await asyncio.to_thread(
        subprocess.run,
        [
            sys.executable,
            str(resource_crate / "bundle.py"),
            "--manifest-path",
            str(manifest),
            "--integration",
            str(target),
        ],
        check=True,
        capture_output=True,
    )
    for relative in ("strings.json", "translations/en.json"):
        before = json.loads(originals[relative])
        after = json.loads((target / relative).read_bytes())
        del before["issues"]["version_mismatch"]["fix_flow"]
        shared = after["issues"]["version_mismatch"].pop("fix_flow")
        assert after == before
        assert "old_key" not in shared["abort"]
    assert (target / "translations/fr.json").read_bytes() == originals[
        "translations/fr.json"
    ]

    loaded = mock_integration(
        hass, MockModule("example"), built_in=False, top_level_files={"translations"}
    )
    loaded.file_path = target
    translations = await async_get_translations(hass, "en", "issues", {"example"})
    prefix = "component.example.issues.version_mismatch.fix_flow"
    assert translations[f"{prefix}.step.retry.submit"] == "Retry version check"
    assert (
        translations[f"{prefix}.step.retry.title"] == "Check the version repair again"
    )
    assert translations[f"{prefix}.error.managed_update_unavailable"] == (
        "Home Assistant could not find the matching managed update entities. "
        "Check the app and Marketplace installations."
    )
    assert translations["component.example.issues.version_mismatch.title"] == (
        "Keep fictional mismatch"
    )
    assert translations["component.example.issues.other_issue.description"] == (
        "Keep unrelated description"
    )


def test_translation_replacement_failure_restores_all_owned_outputs(
    resource_crate: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kit = LockedKit(root=resource_crate, revision="1" * 40, tag=f"v{KIT_VERSION}")
    target = integration(tmp_path / "example", "example")
    bundle(kit, target)
    # Simulate a prior Kit release whose valid generated files remain owned.
    for relative in ("strings.json", "translations/en.json"):
        data = json.loads((target / relative).read_text())
        data["issues"]["version_mismatch"]["fix_flow"] = {"old": "Keep on failure"}
        (target / relative).write_text(json.dumps(data))
    before = {
        p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()
    }
    rename = Path.rename

    def fail_last_translation(path: Path, destination: Path) -> Path:
        if path.name == "translation-1.json":
            raise OSError("Fictional replacement failure")
        return rename(path, destination)

    monkeypatch.setattr(Path, "rename", fail_last_translation)
    with pytest.raises(OSError, match="Fictional replacement failure"):
        bundle(kit, target)
    assert {
        p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()
    } == before
    assert not list(target.glob(".app-kit-*"))


def test_packaged_brand_cli_checks_native_app_and_marketplace_icons(
    resource_crate: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CARGO_NET_OFFLINE", "true")
    manifest = consumer(tmp_path / "consumer", resource_crate)
    app = tmp_path / "app"
    app.mkdir()
    (app / "config.yaml").write_text('panel_icon: "mdi:mailbox-outline"\n')
    (app / "logo.png").write_bytes(b"old App logo")
    target = integration(tmp_path / "example", "example")
    brand = target / "brand"
    brand.mkdir()
    (brand / "dark_logo@2x.png").write_bytes(b"old dark brand logo")
    command = [
        sys.executable,
        str(resource_crate / "brand.py"),
        "--manifest-path",
        str(manifest),
        "--app",
        str(app),
        "--integration",
        str(target),
    ]
    subprocess.run([*command, "--sync"], check=True, capture_output=True)
    subprocess.run([*command, "--check"], check=True, capture_output=True)

    for path, size in (
        (app / "icon.png", 128),
        (brand / "icon.png", 256),
        (brand / "icon@2x.png", 512),
        (brand / "dark_icon.png", 256),
        (brand / "dark_icon@2x.png", 512),
    ):
        png = path.read_bytes()
        assert png.startswith(b"\x89PNG\r\n\x1a\n")
        assert int.from_bytes(png[16:20]) == int.from_bytes(png[20:24]) == size
    assert (app / "logo.png").read_bytes() == (brand / "icon@2x.png").read_bytes()
    assert (brand / "dark_logo@2x.png").read_bytes() == (
        brand / "dark_icon@2x.png"
    ).read_bytes()
    license_text = (target / "ICON-LICENSE.txt").read_text()
    assert license_text == (app / "ICON-LICENSE.txt").read_text()
    assert "Michael Richins" in license_text and "Apache License" in license_text

    other_tile = (resource_crate / "icons/png/hanger/app-icon.png").read_bytes()
    (app / "icon.png").write_bytes(other_tile)
    (brand / "dark_icon.png").unlink()
    rejected = subprocess.run([*command, "--check"], capture_output=True, text=True)
    assert rejected.returncode == 1
    assert str(app / "icon.png") in rejected.stderr
    assert str(brand / "dark_icon.png") in rejected.stderr
    assert (app / "icon.png").read_bytes() == other_tile
    assert not (brand / "dark_icon.png").exists()
    subprocess.run([*command, "--sync"], check=True, capture_output=True)
    subprocess.run([*command, "--check"], check=True, capture_output=True)


async def test_independent_vendored_modules_share_native_lifecycle(
    resource_crate: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hass: HomeAssistant,
) -> None:
    kit = LockedKit(root=resource_crate, revision="1" * 40, tag=f"v{KIT_VERSION}")
    for domain in ("first", "second"):
        bundle(kit, integration(tmp_path / domain, domain))
    monkeypatch.syspath_prepend(str(tmp_path))
    first = importlib.import_module("first._app_kit.repairs")
    second = importlib.import_module("second._app_kit.repairs")
    assert first is not second
    left, right = first._lifecycle(hass), second._lifecycle(hass)
    async with left.lock:
        assert right.lock.locked()
        left.restarting.set()
        assert right.restarting.is_set()
