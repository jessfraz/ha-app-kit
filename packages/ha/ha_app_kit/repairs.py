"""Native version repairs; clients and credentials remain in each companion."""

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import uuid4

from homeassistant.components.backup import async_get_manager
from homeassistant.components.backup.manager import BackupManagerState
from homeassistant.components.backup.models import BaseBackup, Folder
from homeassistant.components.repairs import RepairsFlow, RepairsFlowResult
from homeassistant.components.update import UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.hassio import is_hassio

from .versions import (
    ReleaseVersion,
    RepairReason,
    RepairUnavailable,
    UpdatePlan,
    plan_update,
)

type VersionProbe = Callable[[HomeAssistant, ConfigEntry], Awaitable[ReleaseVersion]]
type SlugResolver = Callable[[ConfigEntry], str | None]
_LIFECYCLE_KEY = "ha_app_kit_version_repairs"
_READINESS_TIMEOUT_SECONDS = 30


async def _async_installed_apps(hass: HomeAssistant) -> dict[str, str]:
    # Core-only installations do not install Supervisor's optional client.
    from homeassistant.components.hassio.handler import get_supervisor_client

    installed = await get_supervisor_client(hass).addons.list()
    apps = {item.slug: item.version for item in installed}
    if len(apps) != len(installed):
        raise RepairUnavailable(RepairReason.VERIFY_FAILED)
    return apps


@dataclass(frozen=True, slots=True)
class VersionRepairSpec:
    domain: str
    name: str
    repository_id: str
    loaded_version: ReleaseVersion
    probe: VersionProbe
    app_slug: SlugResolver

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", self.domain):
            raise ValueError("Invalid integration domain")
        if not self.repository_id.isascii() or not self.repository_id.isdecimal():
            raise ValueError("Invalid repository identity")


@dataclass(frozen=True, slots=True)
class _Lifecycle:
    lock: asyncio.Lock
    restarting: asyncio.Event


def _lifecycle(hass: HomeAssistant) -> _Lifecycle:
    # Vendored copies have different Python module identities. Store only stdlib
    # primitives in HA-owned state so every app shares one lifecycle boundary.
    if _LIFECYCLE_KEY not in hass.data:
        hass.data[_LIFECYCLE_KEY] = {
            "lock": asyncio.Lock(),
            "restarting": asyncio.Event(),
        }
    state = hass.data[_LIFECYCLE_KEY]
    if not isinstance(state, dict):
        raise RuntimeError("Invalid shared repair lifecycle")
    lock, restarting = state.get("lock"), state.get("restarting")
    if not isinstance(lock, asyncio.Lock) or not isinstance(restarting, asyncio.Event):
        raise RuntimeError("Invalid shared repair lifecycle")
    return _Lifecycle(lock, restarting)


@dataclass(frozen=True, slots=True)
class _Snapshot:
    app: ReleaseVersion
    staged: ReleaseVersion
    app_latest: ReleaseVersion | None
    companion_latest: ReleaseVersion
    app_entity: str | None
    companion_entity: str

    def plan(self, loaded: ReleaseVersion) -> UpdatePlan:
        return plan_update(
            app=self.app,
            loaded=loaded,
            staged=self.staged,
            app_latest=self.app_latest,
            # Native update entities advertise the currently available release.
            # When history is unknown, update to a known matching latest pair.
            published_tags=frozenset({self.companion_latest.tag}),
        )


@dataclass(frozen=True, slots=True)
class Applied:
    restart_requested: bool


@dataclass(frozen=True, slots=True)
class Failed:
    reason: RepairReason


type ApplyResult = Applied | Failed


class VersionRepairs:
    """One entry's evidence and a single, explicit native update operation."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, spec: VersionRepairSpec
    ) -> None:
        if entry.domain != spec.domain:
            raise ValueError("Repair entry belongs to another integration")
        self.hass = hass
        self.entry = entry
        self.spec = spec
        self._entry_data = entry.data
        self._entry_options = entry.options
        self._entry_runtime = getattr(entry, "runtime_data", None)
        self._stopped = False
        self.issue_id = f"{entry.entry_id}_version_mismatch"
        self.lifecycle = _lifecycle(hass)

    @callback
    def async_start(self) -> None:
        """A loaded callback owns a fresh check even when entities are disabled."""
        self.entry.async_on_unload(
            self.entry.async_on_state_change(self._async_entry_state_changed)
        )
        self.entry.async_on_unload(self._async_stop)
        self._async_entry_state_changed()

    @callback
    def _async_stop(self) -> None:
        self._stopped = True

    def _assert_owner(self) -> None:
        if (
            self._stopped
            or self.hass.config_entries.async_get_entry(self.entry.entry_id)
            is not self.entry
            or self.entry.disabled_by is not None
            or self.entry.state is not ConfigEntryState.LOADED
            or self.entry.data != self._entry_data
            or self.entry.options != self._entry_options
            or getattr(self.entry, "runtime_data", None) is not self._entry_runtime
        ):
            raise RepairUnavailable(RepairReason.ENTRY_UNAVAILABLE)

    @callback
    def _async_entry_state_changed(self) -> None:
        if not self._stopped and self.entry.state is ConfigEntryState.LOADED:
            self.entry.async_create_background_task(
                self.hass, self.async_check(), "Verify loaded companion version"
            )

    async def async_check(self) -> None:
        """Unknown transport or setup state cannot clear an incident."""
        try:
            version = await self.async_probe()
        except RepairUnavailable:
            return
        self.async_report(version)

    async def async_probe(self) -> ReleaseVersion:
        self._assert_owner()
        try:
            version = await self.spec.probe(self.hass, self.entry)
            self._assert_owner()
            if not isinstance(version, ReleaseVersion):
                raise ValueError("Invalid backend version")
            return version
        except RepairUnavailable:
            raise
        except Exception:
            # The owner may raise a transport exception containing its private
            # URL. Only the fixed reason crosses into the shared flow/registry.
            raise RepairUnavailable(RepairReason.VERIFY_FAILED) from None

    @callback
    def async_report(self, version: ReleaseVersion) -> None:
        """Call only after a successful fresh backend observation."""
        try:
            self._assert_owner()
        except RepairUnavailable:
            return
        registry = ir.async_get(self.hass)
        if version == self.spec.loaded_version:
            if self.entry.state is ConfigEntryState.LOADED:
                ir.async_delete_issue(self.hass, self.spec.domain, self.issue_id)
        else:
            existing = registry.async_get_issue(self.spec.domain, self.issue_id)
            data = dict(existing.data or {}) if existing else {}
            data["entry_id"] = self.entry.entry_id
            ir.async_create_issue(
                self.hass,
                self.spec.domain,
                self.issue_id,
                config_entry_id=self.entry.entry_id,
                is_fixable=True,
                is_persistent=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key="version_mismatch",
                translation_placeholders={
                    "app_version": str(version),
                    "integration_version": str(self.spec.loaded_version),
                },
                data=data,
            )
        # The old global ID had no entry ownership. Migrate it only when the
        # single configured entry makes that ownership unambiguous, after the
        # fresh observation has established its replacement or loaded parity.
        if len(self.hass.config_entries.async_entries(self.spec.domain)) == 1 and (
            version != self.spec.loaded_version
            or self.entry.state is ConfigEntryState.LOADED
        ):
            ir.async_delete_issue(self.hass, self.spec.domain, "version_mismatch")

    def _slug(self) -> str | None:
        slug = self.spec.app_slug(self.entry)
        if slug is not None and not re.fullmatch(r"[a-z0-9_]+", slug):
            raise RepairUnavailable(RepairReason.MANAGED_UPDATE_UNAVAILABLE)
        return slug

    def _state(self, entity_id: str) -> State:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in {STATE_UNAVAILABLE, STATE_UNKNOWN}:
            raise RepairUnavailable(RepairReason.MANAGED_UPDATE_UNAVAILABLE)
        features = state.attributes.get("supported_features")
        if (
            isinstance(features, bool)
            or not isinstance(features, int)
            or not features & UpdateEntityFeature.INSTALL
        ):
            raise RepairUnavailable(RepairReason.MANAGED_UPDATE_UNAVAILABLE)
        progress = state.attributes.get("in_progress")
        # Numeric zero is an update at 0%, not an idle False boolean.
        if progress is not None and progress is not False:
            raise RepairUnavailable(RepairReason.UPDATE_IN_PROGRESS)
        return state

    async def async_snapshot(self) -> _Snapshot:
        self._assert_owner()
        registry = er.async_get(self.hass)
        companion = registry.async_get_entity_id(
            "update", "marketplace", self.spec.repository_id
        )
        if companion is None:
            raise RepairUnavailable(RepairReason.MANAGED_UPDATE_UNAVAILABLE)
        slug = self._slug()
        app_entity = (
            registry.async_get_entity_id("update", "hassio", f"{slug}_version_latest")
            if slug is not None
            else None
        )
        ids = [companion, *([app_entity] if app_entity else [])]
        await self.hass.services.async_call(
            "homeassistant", "update_entity", {"entity_id": ids}, blocking=True
        )
        companion_state = self._state(companion)
        if (
            not companion_state.attributes["supported_features"]
            & UpdateEntityFeature.SPECIFIC_VERSION
        ):
            raise RepairUnavailable(RepairReason.MANAGED_UPDATE_UNAVAILABLE)
        app = await self.async_probe()
        app_latest = None
        if app_entity:
            app_state = self._state(app_entity)
            if (
                ReleaseVersion.parse(app_state.attributes.get("installed_version"))
                != app
            ):
                raise RepairUnavailable(RepairReason.VERIFY_FAILED)
            app_latest = ReleaseVersion.parse(
                app_state.attributes.get("latest_version")
            )
        return _Snapshot(
            app=app,
            staged=ReleaseVersion.parse(
                companion_state.attributes.get("installed_version")
            ),
            app_latest=app_latest,
            companion_latest=ReleaseVersion.parse(
                companion_state.attributes.get("latest_version")
            ),
            app_entity=app_entity,
            companion_entity=companion,
        )

    async def _async_ready_snapshot(self) -> _Snapshot:
        # Cold app backups and native updates can finish before their HTTP
        # listener is ready. Retry only reads; never repeat an update operation.
        try:
            async with asyncio.timeout(_READINESS_TIMEOUT_SECONDS):
                while True:
                    try:
                        return await self.async_snapshot()
                    except RepairUnavailable as err:
                        if err.reason is not RepairReason.VERIFY_FAILED:
                            raise
                    await asyncio.sleep(1)
        except TimeoutError:
            raise RepairUnavailable(RepairReason.VERIFY_FAILED) from None

    @callback
    def _phase(self, operation: str, target: ReleaseVersion, phase: str) -> None:
        issue = ir.async_get(self.hass).async_get_issue(self.spec.domain, self.issue_id)
        if issue is None:
            return
        data = dict(issue.data or {}) | {
            "entry_id": self.entry.entry_id,
            "operation": operation,
            "target_version": str(target),
            "phase": phase,
        }
        ir.async_create_issue(
            self.hass,
            self.spec.domain,
            self.issue_id,
            config_entry_id=self.entry.entry_id,
            is_fixable=True,
            is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="version_mismatch",
            translation_placeholders=issue.translation_placeholders,
            data=data,
        )

    async def _async_backup(self, operation: str, app: ReleaseVersion) -> None:
        try:
            manager = async_get_manager(self.hass)
        except HomeAssistantError:
            raise RepairUnavailable(RepairReason.BACKUP_NOT_CONFIGURED) from None
        config = manager.config.data.create_backup
        slug = self._slug()
        agents = frozenset(config.agent_ids)
        if (
            not agents
            or not config.password
            or not agents.issubset(manager.backup_agents)
        ):
            raise RepairUnavailable(RepairReason.BACKUP_NOT_CONFIGURED)
        if manager.state is not BackupManagerState.IDLE:
            raise RepairUnavailable(RepairReason.UPDATE_IN_PROGRESS)
        supervised = is_hassio(self.hass)
        if slug is not None and not supervised:
            raise RepairUnavailable(RepairReason.BACKUP_NOT_CONFIGURED)
        apps: dict[str, str] = {}
        if supervised:
            try:
                apps = await _async_installed_apps(self.hass)
            except RepairUnavailable:
                raise
            except Exception:
                raise RepairUnavailable(RepairReason.BACKUP_FAILED) from None
            if slug is not None and apps.get(slug) != str(app):
                raise RepairUnavailable(RepairReason.VERIFY_FAILED)
        folders = frozenset(Folder) if supervised else frozenset()
        try:
            await manager.async_create_backup(
                agent_ids=sorted(agents),
                extra_metadata={"ha_app_kit_update": operation},
                include_addons=None,
                include_all_addons=supervised,
                include_database=True,
                include_folders=sorted(folders) or None,
                include_homeassistant=True,
                name=f"Before updating {self.spec.name}",
                password=config.password,
                with_automatic_settings=False,
            )
            backups, errors = await manager.async_get_backups()
        except Exception:
            raise RepairUnavailable(RepairReason.BACKUP_FAILED) from None
        matches = [
            backup
            for backup in backups.values()
            if backup.extra_metadata.get("ha_app_kit_update") == operation
        ]
        if len(matches) != 1 or any(agent in errors for agent in agents):
            raise RepairUnavailable(RepairReason.BACKUP_FAILED)
        backup = matches[0]

        def complete(value: BaseBackup) -> bool:
            return (
                value.backup_id == backup.backup_id
                and value.extra_metadata.get("ha_app_kit_update") == operation
                and value.homeassistant_included
                and value.database_included
                and folders.issubset(value.folders)
                and len(value.addons) == len(apps)
                and apps == {item.slug: item.version for item in value.addons}
            )

        if (
            not complete(backup)
            or backup.failed_addons
            or backup.failed_folders
            or backup.failed_agent_ids
            or not agents.issubset(backup.agents)
            or any(
                not backup.agents[agent].protected or backup.agents[agent].size <= 0
                for agent in agents
            )
            or len({backup.agents[agent].size for agent in agents}) != 1
        ):
            raise RepairUnavailable(RepairReason.BACKUP_FAILED)
        for agent_id in sorted(agents):
            self._assert_owner()
            try:
                copy = await manager.backup_agents[agent_id].async_get_backup(
                    backup.backup_id
                )
            except Exception:
                raise RepairUnavailable(RepairReason.BACKUP_FAILED) from None
            if (
                not complete(copy)
                or not copy.protected
                or copy.size <= 0
                or copy.size != backup.agents[agent_id].size
            ):
                raise RepairUnavailable(RepairReason.BACKUP_FAILED)

    async def async_apply(self, confirmed: UpdatePlan) -> ApplyResult:
        """A closed dialog cannot cancel an already dispatched native update."""
        async with self.lifecycle.lock:
            if self.lifecycle.restarting.is_set():
                return Failed(RepairReason.RESTART_PENDING)
            operation = uuid4().hex
            try:
                snapshot = await self.async_snapshot()
                plan = snapshot.plan(self.spec.loaded_version)
                if plan.target != confirmed.target:
                    return Failed(RepairReason.VERIFY_FAILED)
                self._phase(operation, plan.target, "backup")
                await self._async_backup(operation, snapshot.app)
                snapshot = await self._async_ready_snapshot()
                plan = snapshot.plan(self.spec.loaded_version)
                if plan.target != confirmed.target:
                    return Failed(RepairReason.VERIFY_FAILED)
                if plan.update_companion:
                    self._assert_owner()
                    self._phase(operation, plan.target, "companion_update")
                    await self.hass.services.async_call(
                        "update",
                        "install",
                        {
                            "entity_id": snapshot.companion_entity,
                            "version": plan.target.tag,
                        },
                        blocking=True,
                    )
                    snapshot = await self.async_snapshot()
                    if snapshot.staged != plan.target or snapshot.app > plan.target:
                        return Failed(RepairReason.VERIFY_FAILED)
                if plan.update_app:
                    # Supervisor accepts latest only. Recheck that the native
                    # catalog still offers the exact pair confirmed above.
                    snapshot = await self.async_snapshot()
                    if snapshot.app > plan.target or snapshot.staged != plan.target:
                        return Failed(RepairReason.VERIFY_FAILED)
                    if snapshot.app != plan.target:
                        if (
                            snapshot.app_latest != plan.target
                            or not snapshot.app_entity
                        ):
                            return Failed(RepairReason.VERIFY_FAILED)
                        self._phase(operation, plan.target, "app_update")
                        await self.hass.services.async_call(
                            "update",
                            "install",
                            {"entity_id": snapshot.app_entity, "backup": False},
                            blocking=True,
                        )
                final = await self._async_ready_snapshot()
                if final.app != plan.target or final.staged != plan.target:
                    return Failed(RepairReason.VERIFY_FAILED)
                if plan.restart:
                    self._assert_owner()
                    self._phase(operation, plan.target, "restart_requested")
                    self.lifecycle.restarting.set()
                    try:
                        await self.hass.services.async_call(
                            "homeassistant", "restart", blocking=True
                        )
                    except Exception:
                        # Native Supervisor failures are not HomeAssistantError.
                        # Shutdown cancellation still propagates with the latch
                        # set, since CancelledError is a BaseException.
                        self.lifecycle.restarting.clear()
                        return Failed(RepairReason.RESTART_FAILED)
                    return Applied(restart_requested=True)
                observed = await self.async_probe()
                self.async_report(observed)
                if (
                    observed != self.spec.loaded_version
                    or self.entry.state is not ConfigEntryState.LOADED
                ):
                    return Failed(RepairReason.VERIFY_FAILED)
                return Applied(restart_requested=False)
            except RepairUnavailable as err:
                return Failed(err.reason)
            except Exception:
                # Provider errors can contain private URLs. The flow keeps the
                # incident and reconciles native versions before another write.
                return Failed(RepairReason.UPDATE_FAILED)


class VersionFixFlow(RepairsFlow):
    """One explicit confirmation, native progress, and no premature issue clear."""

    def __init__(self, repairs: VersionRepairs) -> None:
        self.repairs = repairs
        self._plan: UpdatePlan | None = None
        self._operation: asyncio.Task[ApplyResult] | None = None
        self._progress: asyncio.Task[ApplyResult] | None = None

    async def async_step_init(
        self, user_input: dict[str, object] | None = None
    ) -> RepairsFlowResult:
        try:
            if self.repairs.lifecycle.restarting.is_set():
                raise RepairUnavailable(RepairReason.RESTART_PENDING)
            if self.repairs.lifecycle.lock.locked():
                raise RepairUnavailable(RepairReason.UPDATE_IN_PROGRESS)
            version = await self.repairs.async_probe()
            if version == self.repairs.spec.loaded_version and (
                self.repairs.entry.state is ConfigEntryState.LOADED
            ):
                self.repairs.async_report(version)
                return self.async_create_entry(title="", data={})
            snapshot = await self.repairs.async_snapshot()
            self._plan = snapshot.plan(self.repairs.spec.loaded_version)
        except RepairUnavailable as err:
            return self.async_abort(reason=err.reason)
        except HomeAssistantError, ValueError:
            return self.async_abort(reason=RepairReason.MANAGED_UPDATE_UNAVAILABLE)
        action = "update_and_restart" if self._plan.restart else "update_app"
        if self._plan.restart and not (
            self._plan.update_app or self._plan.update_companion
        ):
            action = "restart"
        return self.async_show_menu(
            step_id="init",
            menu_options=[action],
            description_placeholders={
                "app": self.repairs.spec.name,
                "app_version": str(snapshot.app),
                "integration_version": str(self.repairs.spec.loaded_version),
                "target_version": str(self._plan.target),
            },
        )

    async def async_step_update_and_restart(
        self, user_input: dict[str, object] | None = None
    ) -> RepairsFlowResult:
        return await self.async_step_apply()

    async def async_step_update_app(
        self, user_input: dict[str, object] | None = None
    ) -> RepairsFlowResult:
        return await self.async_step_apply()

    async def async_step_restart(
        self, user_input: dict[str, object] | None = None
    ) -> RepairsFlowResult:
        return await self.async_step_apply()

    async def _async_wait_operation(self) -> ApplyResult:
        if self._operation is None:
            return Failed(RepairReason.UPDATE_FAILED)
        return await asyncio.shield(self._operation)

    async def async_step_apply(
        self, user_input: dict[str, object] | None = None
    ) -> RepairsFlowResult:
        if self._plan is None:
            return await self.async_step_init()
        if self._operation is None:
            # HA owns this task once the user confirms. The flow's cancellable
            # progress waiter cannot turn a disconnected UI into a blind retry.
            self._operation = self.hass.async_create_background_task(
                self.repairs.async_apply(self._plan), "Repair app version mismatch"
            )
            self._progress = self.hass.async_create_task(
                self._async_wait_operation(), "Wait for version repair"
            )
        if self._progress is not None and not self._progress.done():
            return self.async_show_progress(
                step_id="apply",
                progress_action="updating",
                progress_task=self._progress,
            )
        return self.async_show_progress_done(next_step_id="finish")

    async def async_step_finish(
        self, user_input: dict[str, object] | None = None
    ) -> RepairsFlowResult:
        if self._operation is None or not self._operation.done():
            return await self.async_step_apply()
        result = self._operation.result()
        if isinstance(result, Failed):
            return self.async_abort(reason=result.reason)
        if result.restart_requested:
            # CREATE_ENTRY deletes the issue. Only a fresh loaded check after
            # the new process starts is allowed to establish matching versions.
            return self.async_abort(reason="restart_requested")
        return self.async_create_entry(title="", data={})


class _UnavailableFixFlow(RepairsFlow):
    """An unowned or stale issue cannot fall back to a dismiss-only repair."""

    async def async_step_init(
        self, user_input: dict[str, object] | None = None
    ) -> RepairsFlowResult:
        return self.async_abort(reason=RepairReason.ENTRY_UNAVAILABLE)


@callback
def create_version_fix_flow(
    hass: HomeAssistant, issue_id: str, spec: VersionRepairSpec
) -> VersionFixFlow | _UnavailableFixFlow:
    issue = ir.async_get(hass).async_get_issue(spec.domain, issue_id)
    if issue is None or not isinstance(issue.config_entry_id, str):
        return _UnavailableFixFlow()
    entry = hass.config_entries.async_get_entry(issue.config_entry_id)
    if (
        entry is None
        or entry.domain != spec.domain
        or issue_id != f"{entry.entry_id}_version_mismatch"
        or not issue.data
        or issue.data.get("entry_id") != entry.entry_id
    ):
        return _UnavailableFixFlow()
    return VersionFixFlow(VersionRepairs(hass, entry, spec))
