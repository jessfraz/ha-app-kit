"""Failed native setup still offers the same protected, explicit repair."""

import asyncio
from collections.abc import Iterator
from dataclasses import replace
from unittest.mock import Mock

import pytest
from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryDisabler,
    ConfigEntryState,
    ConfigFlow,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import (
    MockModule,
    mock_config_flow,
    mock_integration,
    mock_platform,
)
from pytest_homeassistant.typing import ClientSessionGenerator

from ha_app_kit.repairs import (
    Applied,
    Failed,
    VersionFixFlow,
    async_check_startup_version,
    async_report_startup_version,
    create_version_fix_flow,
)
from ha_app_kit.versions import ReleaseVersion, RepairReason
from tests.conftest import NativeRepair


@pytest.fixture
def entry_state() -> ConfigEntryState:
    return ConfigEntryState.NOT_LOADED


@pytest.fixture(autouse=True)
def config_flow() -> Iterator[None]:
    with mock_config_flow("example", ConfigFlow):
        yield


async def setup_startup_repair(
    native: NativeRepair, *, managed: bool = True, observed: bool = False
) -> str:
    spec = native.repairs(managed=managed).spec

    async def setup(hass: HomeAssistant, entry: ConfigEntry) -> None:
        if observed:
            async_report_startup_version(
                hass, entry, spec, ReleaseVersion.parse(native.app)
            )
        else:
            await async_check_startup_version(hass, entry, spec)
        raise ConfigEntryNotReady("A required projection endpoint is unavailable")

    async def create(
        hass: HomeAssistant, issue_id: str, data: dict[str, object] | None
    ) -> RepairsFlow:
        return create_version_fix_flow(hass, issue_id, spec)

    mock_integration(native.hass, MockModule("example", async_setup_entry=setup))
    mock_platform(native.hass, "example.config_flow")
    mock_platform(native.hass, "example.repairs", Mock(async_create_fix_flow=create))
    assert await async_setup_component(native.hass, "example", {})
    assert native.entry.state is ConfigEntryState.SETUP_RETRY
    assert getattr(native.entry, "runtime_data", None) is None
    assert await async_setup_component(native.hass, "repairs", {})
    return f"{native.entry.entry_id}_version_mismatch"


@pytest.mark.parametrize("observed", [False, True], ids=["probe", "observation"])
async def test_native_failed_setup_offers_confirmation_and_cancel_is_inert(
    native: NativeRepair, hass_client: ClientSessionGenerator, observed: bool
) -> None:
    issue_id = await setup_startup_repair(native, observed=observed)
    issue = ir.async_get(native.hass).async_get_issue("example", issue_id)
    assert issue is not None and issue.is_fixable and issue.is_persistent
    assert issue.config_entry_id == native.entry.entry_id
    assert issue.data == {
        "entry_id": native.entry.entry_id,
        "startup_revision": native.entry.modified_at.isoformat(),
    }
    listeners = tuple(native.entry._on_state_change or ())
    client = await hass_client()
    response = await client.post(
        "/api/repairs/issues/fix",
        json={"handler": "example", "issue_id": issue_id},
    )
    assert response.status == 200
    confirmation = await response.json()
    assert confirmation["type"] == "menu", confirmation
    assert confirmation["menu_options"] == ["update_and_restart"]
    assert len(native.entry._on_state_change or ()) == len(listeners) + 1
    assert native.events == []
    assert (
        await client.delete(f"/api/repairs/issues/fix/{confirmation['flow_id']}")
    ).status == 200
    assert native.events == []
    assert ir.async_get(native.hass).async_get_issue("example", issue_id) is issue
    assert tuple(native.entry._on_state_change or ()) == listeners


async def test_startup_native_retry_refreshes_evidence_without_mutating(
    native: NativeRepair, hass_client: ClientSessionGenerator
) -> None:
    issue_id = await setup_startup_repair(native)
    registry = er.async_get(native.hass)
    registry.async_remove(native.companion_entity)
    client = await hass_client()
    response = await client.post(
        "/api/repairs/issues/fix",
        json={"handler": "example", "issue_id": issue_id},
    )
    retry = await response.json()
    assert retry["type"] == "form" and retry["step_id"] == "retry"
    assert retry["errors"] == {"base": "managed_update_unavailable"}
    native.companion_entity = registry.async_get_or_create(
        "update", "marketplace", "123456"
    ).entity_id
    native.states()
    response = await client.post(f"/api/repairs/issues/fix/{retry['flow_id']}", json={})
    confirmation = await response.json()
    assert confirmation["type"] == "menu", confirmation
    assert confirmation["menu_options"] == ["update_and_restart"]
    assert native.events == []
    assert (
        await client.delete(f"/api/repairs/issues/fix/{retry['flow_id']}")
    ).status == 200


async def test_closing_progress_keeps_startup_owner_until_the_operation_finishes(
    native: NativeRepair, hass_client: ClientSessionGenerator
) -> None:
    issue_id = await setup_startup_repair(native)
    listeners = tuple(native.entry._on_state_change or ())
    native.backup_release = asyncio.Event()
    client = await hass_client()
    response = await client.post(
        "/api/repairs/issues/fix",
        json={"handler": "example", "issue_id": issue_id},
    )
    menu = await response.json()
    response = await client.post(
        f"/api/repairs/issues/fix/{menu['flow_id']}",
        json={"next_step_id": "update_and_restart"},
    )
    assert (await response.json())["type"] == "progress"
    await native.backup_started.wait()
    assert (
        await client.delete(f"/api/repairs/issues/fix/{menu['flow_id']}")
    ).status == 200
    # Cancellation cannot abandon an uncertain backup or release its owner.
    assert len(native.entry._on_state_change or ()) == len(listeners) + 1
    assert await native.hass.config_entries.async_unload(native.entry.entry_id)
    await native.entry.async_setup_locked(native.hass)
    assert native.entry.state is ConfigEntryState.SETUP_RETRY
    native.backup_release.set()
    await native.hass.async_block_till_done(wait_background_tasks=True)
    assert "app" not in native.events and "companion" not in native.events
    assert "restart" not in native.events
    assert tuple(native.entry._on_state_change or ()) == listeners
    assert ir.async_get(native.hass).async_get_issue("example", issue_id)


@pytest.mark.parametrize("backend_only", [False, True])
async def test_startup_updates_are_backed_up_and_remain_open_until_loaded_parity(
    native: NativeRepair, backend_only: bool
) -> None:
    if backend_only:
        native.app = "0.8.0"
        native.staged = "0.9.0"
        native.latest = "0.9.0"
        native.states()
    issue_id = await setup_startup_repair(native)
    repair = create_version_fix_flow(native.hass, issue_id, native.repairs().spec)
    assert isinstance(repair, VersionFixFlow)
    repair.hass = native.hass
    repair.handler = "example"
    repair.flow_id = "fictional-startup-flow"
    result = await repair.async_step_init()
    assert result["type"] == "menu"
    assert result["menu_options"] == ["update_and_restart"]
    native.backup_release = asyncio.Event()
    progress = await repair.async_step_update_and_restart({})
    native.backup_release.set()
    waiter = progress["progress_task"]
    assert waiter is not None
    await waiter
    finish = await repair.async_step_finish()
    assert finish["type"] == "abort" and finish["reason"] == "restart_requested"
    repair.async_remove()
    assert native.events[:4] == [
        "backup",
        "backup_list",
        "verify:local",
        "verify:remote",
    ]
    assert native.events[-1] == "restart"
    assert ir.async_get(native.hass).async_get_issue("example", issue_id)
    # Even fresh matching evidence during SETUP_RETRY cannot clear the incident.
    await async_check_startup_version(native.hass, native.entry, native.repairs().spec)
    assert ir.async_get(native.hass).async_get_issue("example", issue_id)

    async def loaded(hass: HomeAssistant, entry: ConfigEntry) -> None:
        entry.runtime_data = object()
        repairs = native.repairs(loaded=native.app)
        repairs.async_start()

    mock_integration(native.hass, MockModule("example", async_setup_entry=loaded))
    assert await native.hass.config_entries.async_reload(native.entry.entry_id)
    await native.hass.async_block_till_done(wait_background_tasks=True)
    assert native.entry.state is ConfigEntryState.LOADED
    assert ir.async_get(native.hass).async_get_issue("example", issue_id) is None


@pytest.mark.parametrize(
    "fault", ["config", "runtime", "disabled", "unload", "unload_retry"]
)
async def test_startup_owner_change_during_backup_aborts_before_install(
    native: NativeRepair, fault: str
) -> None:
    issue_id = await setup_startup_repair(native)
    repair = create_version_fix_flow(native.hass, issue_id, native.repairs().spec)
    assert isinstance(repair, VersionFixFlow)
    repairs = repair.repairs
    native.backup_release = asyncio.Event()
    plan = (await repairs.async_snapshot()).plan(repairs.spec.loaded_version)
    task = asyncio.create_task(repairs.async_apply(plan))
    await native.backup_started.wait()
    if fault == "config":
        native.hass.config_entries.async_update_entry(native.entry, data={"new": True})
    elif fault == "runtime":
        native.entry.runtime_data = object()
    elif fault == "disabled":
        await native.hass.config_entries.async_set_disabled_by(
            native.entry.entry_id, ConfigEntryDisabler.USER
        )
    else:
        assert await native.hass.config_entries.async_unload(native.entry.entry_id)
        if fault == "unload_retry":
            await native.entry.async_setup_locked(native.hass)
            assert native.entry.state is ConfigEntryState.SETUP_RETRY
    native.backup_release.set()
    assert await task == Failed(RepairReason.ENTRY_UNAVAILABLE)
    assert "app" not in native.events and "companion" not in native.events
    assert "restart" not in native.events
    assert not repairs.lifecycle.lock.locked()
    repair.async_remove()


async def test_scheduled_setup_retry_does_not_invalidate_startup_repair(
    native: NativeRepair,
) -> None:
    issue_id = await setup_startup_repair(native)
    repair = create_version_fix_flow(native.hass, issue_id, native.repairs().spec)
    assert isinstance(repair, VersionFixFlow)
    repairs = repair.repairs
    native.backup_release = asyncio.Event()
    plan = (await repairs.async_snapshot()).plan(repairs.spec.loaded_version)
    task = asyncio.create_task(repairs.async_apply(plan))
    await native.backup_started.wait()
    await native.entry.async_setup_locked(native.hass)
    assert native.entry.state is ConfigEntryState.SETUP_RETRY
    native.backup_release.set()
    assert await task == Applied(restart_requested=True)
    assert native.events.count("backup") == 1
    assert native.events[-1] == "restart"
    repair.async_remove()


async def test_startup_stale_revision_and_unowned_issue_remain_inert(
    native: NativeRepair, hass_client: ClientSessionGenerator
) -> None:
    issue_id = await setup_startup_repair(native)
    native.hass.config_entries.async_update_entry(native.entry, options={"new": True})
    client = await hass_client()
    response = await client.post(
        "/api/repairs/issues/fix",
        json={"handler": "example", "issue_id": issue_id},
    )
    result = await response.json()
    assert result["type"] == "abort" and result["reason"] == "entry_unavailable"
    assert native.events == []
    assert ir.async_get(native.hass).async_get_issue("example", issue_id)


async def test_unknown_startup_probe_preserves_issue_and_logs_no_private_error(
    native: NativeRepair, caplog: pytest.LogCaptureFixture
) -> None:
    issue_id = await setup_startup_repair(native)
    issue = ir.async_get(native.hass).async_get_issue("example", issue_id)
    native.probe_failures = 1
    await async_check_startup_version(native.hass, native.entry, native.repairs().spec)
    assert ir.async_get(native.hass).async_get_issue("example", issue_id) is issue
    failure = [r.getMessage() for r in caplog.records if r.name == "ha_app_kit.repairs"]
    assert failure == [
        "Version repair failed: domain=example stage=startup reason=verify_failed "
        "check=backend_probe loaded_version=0.9.0 app_version=unknown "
        "target_version=unknown"
    ]
    assert native.events == []


@pytest.mark.parametrize("cancel", [False, True], ids=["timeout", "cancellation"])
async def test_startup_probe_is_bounded_and_cancellation_is_inert(
    native: NativeRepair, monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    issue_id = await setup_startup_repair(native)
    issue = ir.async_get(native.hass).async_get_issue("example", issue_id)
    started = asyncio.Event()

    async def wait(hass: HomeAssistant, entry: ConfigEntry) -> ReleaseVersion:
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("An unbounded probe must be cancelled")

    spec = replace(native.repairs().spec, probe=wait)
    monkeypatch.setattr(
        "ha_app_kit.repairs._READINESS_TIMEOUT_SECONDS", 30 if cancel else 0.001
    )
    task = asyncio.create_task(
        async_check_startup_version(native.hass, native.entry, spec)
    )
    await started.wait()
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        await task
    assert ir.async_get(native.hass).async_get_issue("example", issue_id) is issue
    assert native.events == []


async def test_standalone_startup_cannot_update_the_backend(
    native: NativeRepair, hass_client: ClientSessionGenerator
) -> None:
    native.app = "0.8.0"
    native.states()
    issue_id = await setup_startup_repair(native, managed=False)
    client = await hass_client()
    response = await client.post(
        "/api/repairs/issues/fix",
        json={"handler": "example", "issue_id": issue_id},
    )
    result = await response.json()
    assert result["type"] == "form" and result["step_id"] == "retry"
    assert result["errors"] == {"base": "app_update_unavailable"}
    assert native.events == []
    assert (
        await client.delete(f"/api/repairs/issues/fix/{result['flow_id']}")
    ).status == 200
