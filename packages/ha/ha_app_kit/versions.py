"""Forward-only release matching for a backend and its loaded companion."""

import re
from dataclasses import dataclass
from enum import StrEnum

_VERSION = re.compile(r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")


@dataclass(frozen=True, order=True, slots=True)
class ReleaseVersion:
    """The apps publish stable semantic versions under matching v-prefixed tags."""

    major: int
    minor: int
    patch: int

    def __post_init__(self) -> None:
        if any(
            isinstance(part, bool) or not isinstance(part, int) or part < 0
            for part in (self.major, self.minor, self.patch)
        ):
            raise ValueError("Invalid stable release version")

    @classmethod
    def parse(cls, value: object) -> ReleaseVersion:
        if not isinstance(value, str) or len(value) > 64:
            raise ValueError("Expected a stable release version")
        match = _VERSION.fullmatch(value)
        if match is None:
            raise ValueError("Expected a stable release version")
        return cls(*(int(part) for part in match.groups()))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @property
    def tag(self) -> str:
        return f"v{self}"


class RepairReason(StrEnum):
    APP_UPDATE_UNAVAILABLE = "app_update_unavailable"
    MATCHING_RELEASE_UNAVAILABLE = "matching_release_unavailable"
    ENTRY_UNAVAILABLE = "entry_unavailable"
    MANAGED_UPDATE_UNAVAILABLE = "managed_update_unavailable"
    UPDATE_IN_PROGRESS = "update_in_progress"
    BACKUP_NOT_CONFIGURED = "backup_not_configured"
    BACKUP_FAILED = "backup_failed"
    UPDATE_FAILED = "update_failed"
    VERIFY_FAILED = "verify_failed"
    RESTART_FAILED = "restart_failed"
    RESTART_PENDING = "restart_pending"


class RepairCheck(StrEnum):
    ENTRY_OWNER = "entry_owner"
    LIFECYCLE = "lifecycle"
    BACKEND_PROBE = "backend_probe"
    COMPANION_REGISTRY = "companion_registry"
    COMPANION_STATE = "companion_state"
    COMPANION_FEATURES = "companion_features"
    COMPANION_VERSION = "companion_version"
    COMPANION_CATALOG = "companion_catalog"
    APP_IDENTITY = "app_identity"
    APP_STATE = "app_state"
    APP_VERSION = "app_version"
    APP_CATALOG = "app_catalog"
    NATIVE_REFRESH = "native_refresh"
    CATALOG_MATCH = "catalog_match"


class RepairUnavailable(Exception):
    """A fixed, translated reason, never a provider exception or payload."""

    def __init__(self, reason: RepairReason, check: RepairCheck | None = None) -> None:
        self.reason = reason
        self.check = check
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class UpdatePlan:
    """Only native updates needed to reach one matching released version."""

    target: ReleaseVersion
    update_app: bool
    update_companion: bool
    restart: bool


def plan_update(
    *,
    app: ReleaseVersion,
    loaded: ReleaseVersion,
    staged: ReleaseVersion,
    app_latest: ReleaseVersion | None,
    published_tags: frozenset[str],
) -> UpdatePlan:
    """Supervisor installs latest; Marketplace can install an explicit release."""
    target = max(app, loaded, staged)
    if app < target:
        if app_latest is None or app_latest < target:
            raise RepairUnavailable(
                RepairReason.APP_UPDATE_UNAVAILABLE, RepairCheck.CATALOG_MATCH
            )
        target = app_latest

    if target.tag not in published_tags:
        # An older app release can have fallen outside Marketplace's fetched
        # history. A known matching latest pair is still a forward-only repair.
        if (
            app_latest is None
            or app_latest < target
            or app_latest.tag not in published_tags
        ):
            raise RepairUnavailable(
                RepairReason.MATCHING_RELEASE_UNAVAILABLE, RepairCheck.CATALOG_MATCH
            )
        target = app_latest

    return UpdatePlan(
        target=target,
        update_app=app != target,
        update_companion=staged != target,
        restart=loaded != target,
    )
