"""Native HA registries, entries, services and backup models with fictional I/O."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace

import pytest
from homeassistant.components.backup.agent import BackupAgent
from homeassistant.components.backup.const import DATA_MANAGER
from homeassistant.components.backup.manager import (
    AgentBackupStatus,
    BackupManager,
    CoreBackupReaderWriter,
    IdleEvent,
    ManagerBackup,
    NewBackup,
)
from homeassistant.components.backup.models import AddonInfo, AgentBackup, Folder
from homeassistant.components.update import UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry

from ha_app_kit.repairs import VersionRepairs, VersionRepairSpec
from ha_app_kit.versions import ReleaseVersion


class MemoryAgent(BackupAgent):
    """The native agent boundary; copies are never files or external storage."""

    domain = "test"
    name = "Fictional backup"

    def __init__(self, unique_id: str, events: list[str]) -> None:
        self.unique_id = unique_id
        self.copy: AgentBackup | None = None
        self.events = events

    async def async_get_backup(self, backup_id: str, **kwargs: object) -> AgentBackup:
        self.events.append(f"verify:{self.unique_id}")
        assert self.copy is not None and self.copy.backup_id == backup_id
        return self.copy

    async def async_list_backups(self, **kwargs: object) -> list[AgentBackup]:
        return [self.copy] if self.copy is not None else []

    async def async_download_backup(
        self, backup_id: str, **kwargs: object
    ) -> AsyncIterator[bytes]:
        async def stream() -> AsyncIterator[bytes]:
            yield b"fictional"

        return stream()

    async def async_upload_backup(self, **kwargs: object) -> None:
        raise AssertionError("No upload belongs in a repair fixture")

    async def async_delete_backup(self, backup_id: str, **kwargs: object) -> None:
        raise AssertionError("A version repair must not remove backups")


@dataclass
class NativeRepair:
    hass: HomeAssistant
    entry: MockConfigEntry
    manager: BackupManager
    app_entity: str
    companion_entity: str
    events: list[str] = field(default_factory=list)
    app: str = "1.0.0"
    staged: str = "1.0.0"
    latest: str = "1.1.0"
    copies: list[MemoryAgent] = field(default_factory=list)
    backup: ManagerBackup | None = None
    backup_args: dict[str, object] = field(default_factory=dict)
    backup_started: asyncio.Event = field(default_factory=asyncio.Event)
    backup_release: asyncio.Event | None = None
    fault: str | None = None
    install_noop: bool = False
    probe_failures: int = 0
    supervised: bool = True

    def states(self) -> None:
        for identity, installed in (
            (self.app_entity, self.app),
            (self.companion_entity, self.staged),
        ):
            self.hass.states.async_set(
                identity,
                "on",
                {
                    "supported_features": int(
                        UpdateEntityFeature.INSTALL
                        | UpdateEntityFeature.SPECIFIC_VERSION
                    ),
                    "installed_version": installed,
                    "latest_version": self.latest,
                    "in_progress": False,
                },
            )

    def repairs(self, loaded: str = "0.9.0", *, managed: bool = True) -> VersionRepairs:
        async def probe(hass: HomeAssistant, entry: ConfigEntry) -> ReleaseVersion:
            if self.probe_failures:
                self.probe_failures -= 1
                raise OSError("fictional-private-backend-url")
            return ReleaseVersion.parse(self.app)

        return VersionRepairs(
            self.hass,
            self.entry,
            VersionRepairSpec(
                domain="example",
                name="Example",
                repository_id="123456",
                loaded_version=ReleaseVersion.parse(loaded),
                probe=probe,
                app_slug=lambda entry: "example_app" if managed else None,
            ),
        )

    async def create_backup(self, **kwargs: object) -> NewBackup:
        self.events.append("backup")
        self.backup_args = kwargs
        self.backup_started.set()
        if self.backup_release is not None:
            await self.backup_release.wait()
        if self.fault == "capture":
            raise RuntimeError("fictional-private-provider-url")
        metadata = kwargs["extra_metadata"]
        assert isinstance(metadata, dict)
        self.backup = ManagerBackup(
            addons=[
                AddonInfo(name="Example", slug="example_app", version=self.app),
                AddonInfo(name="Other", slug="other_app", version="2.0.0"),
            ]
            if self.supervised
            else [],
            backup_id="fictional-backup",
            date="2026-11-10T12:00:00Z",
            database_included=True,
            extra_metadata=metadata,
            folders=list(Folder) if self.supervised else [],
            homeassistant_included=True,
            homeassistant_version="2026.11.0",
            name="Fictional recovery",
            agents={
                copy.agent_id: AgentBackupStatus(protected=True, size=256)
                for copy in self.copies
            },
            failed_addons=[],
            failed_agent_ids=[],
            failed_folders=[],
            with_automatic_settings=False,
        )
        if self.fault == "folder":
            self.backup = replace(self.backup, folders=[])
        if self.fault == "app":
            self.backup = replace(self.backup, addons=self.backup.addons[:1])
        if self.fault == "upload":
            self.backup = replace(
                self.backup, failed_agent_ids=[self.copies[-1].agent_id]
            )
        for copy in self.copies:
            copy.copy = AgentBackup(
                addons=self.backup.addons,
                backup_id=self.backup.backup_id,
                date=self.backup.date,
                database_included=True,
                extra_metadata=metadata,
                folders=self.backup.folders,
                homeassistant_included=True,
                homeassistant_version="2026.11.0",
                name="Fictional recovery",
                protected=True,
                size=256,
            )
        if self.fault == "unprotected":
            copy = self.copies[-1].copy
            assert copy is not None
            self.copies[-1].copy = replace(copy, protected=False)
        if self.fault == "cold_start":
            self.probe_failures = 1
        return NewBackup(backup_job_id="fictional-job")

    async def backups(self) -> tuple[dict[str, ManagerBackup], dict[str, Exception]]:
        self.events.append("backup_list")
        assert self.backup is not None
        return {self.backup.backup_id: self.backup}, {}


@pytest.fixture
def entry_state() -> ConfigEntryState:
    return ConfigEntryState.LOADED


@pytest.fixture
async def native(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    entry_state: ConfigEntryState,
) -> NativeRepair:
    entry = MockConfigEntry(domain="example", state=entry_state)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    app = registry.async_get_or_create("update", "hassio", "example_app_version_latest")
    companion = registry.async_get_or_create("update", "marketplace", "123456")
    manager = BackupManager(hass, CoreBackupReaderWriter(hass))
    manager.last_event = IdleEvent()
    hass.data[DATA_MANAGER] = manager
    fixture = NativeRepair(hass, entry, manager, app.entity_id, companion.entity_id)
    fixture.copies = [MemoryAgent(name, fixture.events) for name in ("local", "remote")]
    manager.backup_agents = {copy.agent_id: copy for copy in fixture.copies}
    manager.config.data.create_backup.agent_ids = list(manager.backup_agents)
    manager.config.data.create_backup.password = "fictional-encryption-key"
    # A repair must request a full recovery copy even if the schedule is partial.
    manager.config.data.create_backup.include_database = False
    manager.config.data.create_backup.include_all_addons = False
    monkeypatch.setattr(manager, "async_create_backup", fixture.create_backup)
    monkeypatch.setattr(manager, "async_get_backups", fixture.backups)
    monkeypatch.setattr(
        "ha_app_kit.repairs.is_hassio", lambda hass: fixture.supervised, raising=False
    )

    async def installed_apps(hass: HomeAssistant) -> dict[str, str]:
        return {"example_app": fixture.app, "other_app": "2.0.0"}

    monkeypatch.setattr(
        "ha_app_kit.repairs._async_installed_apps", installed_apps, raising=False
    )

    async def refresh(call: ServiceCall) -> None:
        fixture.states()

    async def install(call: ServiceCall) -> None:
        identity = call.data["entity_id"]
        fixture.events.append(
            "companion" if identity == fixture.companion_entity else "app"
        )
        if fixture.install_noop:
            return
        if identity == fixture.companion_entity:
            assert call.data["version"] == f"v{fixture.latest}"
            fixture.staged = fixture.latest
            if fixture.fault == "newer_app":
                fixture.app = "2.0.0"
        else:
            assert identity == fixture.app_entity and "version" not in call.data
            fixture.app = fixture.latest
        fixture.states()

    async def restart(call: ServiceCall) -> None:
        fixture.events.append("restart")

    hass.services.async_register("homeassistant", "update_entity", refresh)
    hass.services.async_register("update", "install", install)
    hass.services.async_register("homeassistant", "restart", restart)
    fixture.states()
    return fixture
