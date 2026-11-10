"""One explicit native repair, protected recovery, and a truthful final issue."""

import asyncio

import pytest
from aiohasupervisor.exceptions import SupervisorConnectionError
from homeassistant.core import ServiceCall
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from ha_app_kit.repairs import Applied, Failed, VersionFixFlow, create_version_fix_flow
from ha_app_kit.versions import ReleaseVersion, RepairReason, RepairUnavailable
from tests.conftest import NativeRepair


def flow(native: NativeRepair) -> VersionFixFlow:
    repairs = native.repairs()
    repairs.async_report(ReleaseVersion.parse(native.app))
    result = VersionFixFlow(repairs)
    result.hass = native.hass
    result.handler = "example"
    result.flow_id = "fictional-flow"
    result.context = {"issue_id": repairs.issue_id}
    return result


async def test_confirmation_full_backup_native_updates_and_restart_keep_issue(
    native: NativeRepair,
) -> None:
    native.backup_release = asyncio.Event()
    repair = flow(native)
    menu = await repair.async_step_init()
    assert menu["type"] is FlowResultType.MENU
    assert native.events == []
    progress = await repair.async_step_update_and_restart({})
    assert progress["type"] is FlowResultType.SHOW_PROGRESS
    assert progress["progress_task"] is not None
    native.backup_release.set()
    await progress["progress_task"]
    finish = await repair.async_step_finish()
    assert finish["type"] is FlowResultType.ABORT
    assert finish["reason"] == "restart_requested"
    assert native.events == [
        "backup",
        "backup_list",
        "verify:local",
        "verify:remote",
        "companion",
        "app",
        "restart",
    ]
    assert native.backup_args["include_all_addons"] is True
    assert native.backup_args["include_database"] is True
    assert native.backup_args["include_homeassistant"] is True
    assert native.backup_args["with_automatic_settings"] is False
    assert native.manager.config.data.create_backup.include_database is False
    assert ir.async_get(native.hass).async_get_issue("example", repair.repairs.issue_id)
    # The new process's loaded code is the only thing that can close the issue.
    new = native.repairs(loaded="1.1.0")
    await new.async_check()
    assert ir.async_get(native.hass).async_get_issue("example", new.issue_id) is None


@pytest.mark.parametrize("fault", ["capture", "upload", "folder", "app", "unprotected"])
async def test_partial_or_unprotected_recovery_never_updates(
    native: NativeRepair, fault: str
) -> None:
    native.fault = fault
    repair = native.repairs()
    snapshot = await repair.async_snapshot()
    result = await repair.async_apply(snapshot.plan(repair.spec.loaded_version))
    assert result == Failed(RepairReason.BACKUP_FAILED)
    assert "app" not in native.events and "companion" not in native.events
    assert "restart" not in native.events
    assert not repair.lifecycle.lock.locked()


async def test_companion_success_requires_readback_before_backend_update(
    native: NativeRepair,
) -> None:
    native.install_noop = True
    repair = native.repairs()
    snapshot = await repair.async_snapshot()
    result = await repair.async_apply(snapshot.plan(repair.spec.loaded_version))
    assert result == Failed(RepairReason.VERIFY_FAILED)
    assert native.events[-1] == "companion"
    assert "app" not in native.events and "restart" not in native.events


async def test_partial_schedule_is_not_the_repair_recovery_scope(
    native: NativeRepair,
) -> None:
    repair = native.repairs()
    plan = (await repair.async_snapshot()).plan(repair.spec.loaded_version)
    assert native.manager.config.data.create_backup.include_database is False
    assert await repair.async_apply(plan) == Applied(restart_requested=True)
    assert native.backup_args["include_database"] is True
    assert native.backup_args["include_all_addons"] is True


async def test_backend_only_update_closes_issue_after_fresh_loaded_parity(
    native: NativeRepair,
) -> None:
    native.staged = "1.1.0"
    native.states()
    repair = native.repairs(loaded="1.1.0")
    repair.async_report(ReleaseVersion.parse(native.app))
    plan = (await repair.async_snapshot()).plan(repair.spec.loaded_version)
    assert not plan.restart and not plan.update_companion and plan.update_app
    assert await repair.async_apply(plan) == Applied(restart_requested=False)
    assert "companion" not in native.events and "restart" not in native.events
    assert ir.async_get(native.hass).async_get_issue("example", repair.issue_id) is None


async def test_cold_backup_waits_for_backend_before_any_update(
    native: NativeRepair,
) -> None:
    native.fault = "cold_start"
    repair = native.repairs()
    plan = (await repair.async_snapshot()).plan(repair.spec.loaded_version)
    assert await repair.async_apply(plan) == Applied(restart_requested=True)
    assert native.events.count("backup") == 1
    assert native.events.count("companion") == 1
    assert native.events.count("app") == 1


@pytest.mark.parametrize(
    "restart_error",
    [HomeAssistantError, SupervisorConnectionError],
    ids=["home_assistant", "supervisor"],
)
async def test_native_restart_failure_releases_lifecycle_and_reconciles_retry(
    native: NativeRepair,
    restart_error: type[Exception],
) -> None:
    repair = native.repairs()
    repair.async_report(ReleaseVersion.parse(native.app))
    plan = (await repair.async_snapshot()).plan(repair.spec.loaded_version)

    async def fail_restart(call: ServiceCall) -> None:
        raise restart_error("fictional-private-url")

    native.hass.services.async_register("homeassistant", "restart", fail_restart)
    assert await repair.async_apply(plan) == Failed(RepairReason.RESTART_FAILED)
    assert not repair.lifecycle.lock.locked()
    assert not repair.lifecycle.restarting.is_set()
    assert ir.async_get(native.hass).async_get_issue("example", repair.issue_id)

    async def restart(call: ServiceCall) -> None:
        native.events.append("restart")

    native.hass.services.async_register("homeassistant", "restart", restart)
    assert await repair.async_apply(plan) == Applied(restart_requested=True)
    assert native.events.count("companion") == 1
    assert native.events.count("app") == 1


async def test_registry_identity_is_required_even_when_an_update_state_exists(
    native: NativeRepair,
) -> None:
    er.async_get(native.hass).async_remove(native.companion_entity)
    with pytest.raises(RepairUnavailable) as failure:
        await native.repairs().async_snapshot()
    assert failure.value.reason is RepairReason.MANAGED_UPDATE_UNAVAILABLE
    assert native.events == []


async def test_stale_issue_factory_aborts_without_a_dismiss_only_fallback(
    native: NativeRepair,
) -> None:
    issue_id = "version_mismatch"
    ir.async_create_issue(
        native.hass,
        "example",
        issue_id,
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="version_mismatch",
    )
    repair = create_version_fix_flow(native.hass, issue_id, native.repairs().spec)
    repair.hass = native.hass
    repair.handler = "example"
    repair.flow_id = "fictional-invalid-flow"
    result = await repair.async_step_init()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "entry_unavailable"
    assert ir.async_get(native.hass).async_get_issue("example", issue_id)
    assert native.events == []


async def test_core_only_installation_uses_native_core_backup_without_apps(
    native: NativeRepair,
) -> None:
    native.supervised = False
    native.app = "1.1.0"
    native.states()
    repair = native.repairs(managed=False)
    plan = (await repair.async_snapshot()).plan(repair.spec.loaded_version)
    assert await repair.async_apply(plan) == Applied(restart_requested=True)
    assert native.backup_args["include_all_addons"] is False
    assert native.backup_args["include_folders"] is None
    assert native.backup_args["include_database"] is True
    assert "app" not in native.events


async def test_a_newer_native_backend_cannot_be_downgraded_after_companion_update(
    native: NativeRepair,
) -> None:
    native.fault = "newer_app"
    repair = native.repairs()
    plan = (await repair.async_snapshot()).plan(repair.spec.loaded_version)
    assert await repair.async_apply(plan) == Failed(RepairReason.VERIFY_FAILED)
    assert native.app == "2.0.0"
    assert "app" not in native.events and "restart" not in native.events


@pytest.mark.parametrize("owner", ["data", "runtime"])
async def test_unloaded_or_changed_owner_cannot_mutate_after_backup(
    native: NativeRepair,
    owner: str,
) -> None:
    native.backup_release = asyncio.Event()
    repair = native.repairs()
    plan = (await repair.async_snapshot()).plan(repair.spec.loaded_version)
    task = asyncio.create_task(repair.async_apply(plan))
    await native.backup_started.wait()
    if owner == "data":
        native.hass.config_entries.async_update_entry(
            native.entry, data={"changed": True}
        )
    else:
        native.entry.runtime_data = object()
    native.backup_release.set()
    assert await task == Failed(RepairReason.ENTRY_UNAVAILABLE)
    assert "app" not in native.events and "restart" not in native.events
    assert not repair.lifecycle.lock.locked()


async def test_dialog_cancellation_does_not_abandon_dispatched_backup(
    native: NativeRepair,
) -> None:
    native.backup_release = asyncio.Event()
    repair = flow(native)
    await repair.async_step_init()
    progress = await repair.async_step_update_and_restart({})
    await native.backup_started.wait()
    waiter = progress["progress_task"]
    assert waiter is not None
    waiter.cancel()
    await asyncio.gather(waiter, return_exceptions=True)
    native.backup_release.set()
    assert repair._operation is not None
    assert await repair._operation == Applied(restart_requested=True)
    assert native.events[-1] == "restart"


async def test_concurrent_repairs_share_one_lifecycle_and_restart_boundary(
    native: NativeRepair,
) -> None:
    native.backup_release = asyncio.Event()
    first, second = native.repairs(), native.repairs()
    plan = (await first.async_snapshot()).plan(first.spec.loaded_version)
    task = asyncio.create_task(first.async_apply(plan))
    await native.backup_started.wait()
    other = asyncio.create_task(second.async_apply(plan))
    await asyncio.sleep(0)
    assert native.events == ["backup"]
    native.backup_release.set()
    assert await task == Applied(restart_requested=True)
    assert await other == Failed(RepairReason.RESTART_PENDING)
    assert native.events.count("backup") == 1
    assert native.events.count("restart") == 1
