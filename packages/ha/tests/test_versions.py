"""Published matching pairs can advance, never silently downgrade."""

import pytest

from ha_app_kit.versions import ReleaseVersion, RepairUnavailable, plan_update


@pytest.mark.parametrize(
    "value", [None, True, "1.2", "1.2.3-beta", "01.2.3", "1.2.3/evil"]
)
def test_only_stable_releases(value: object) -> None:
    with pytest.raises(ValueError):
        ReleaseVersion.parse(value)


@pytest.mark.parametrize(
    ("app", "loaded", "staged", "latest", "published", "target"),
    [
        ("1.0.0", "1.1.0", "1.1.0", "1.1.0", "v1.1.0", "1.1.0"),
        ("1.1.0", "1.0.0", "1.1.0", "1.1.0", "v1.1.0", "1.1.0"),
        ("1.1.0", "1.0.0", "1.2.0", "1.3.0", "v1.3.0", "1.3.0"),
    ],
)
def test_matching_forward_pair(
    app: str, loaded: str, staged: str, latest: str, published: str, target: str
) -> None:
    plan = plan_update(
        app=ReleaseVersion.parse(app),
        loaded=ReleaseVersion.parse(loaded),
        staged=ReleaseVersion.parse(staged),
        app_latest=ReleaseVersion.parse(latest),
        published_tags=frozenset({published}),
    )
    assert str(plan.target) == target
    assert plan.target >= max(
        ReleaseVersion.parse(value) for value in (app, loaded, staged)
    )


def test_an_older_backend_catalog_cannot_downgrade_staged_companion() -> None:
    with pytest.raises(RepairUnavailable):
        plan_update(
            app=ReleaseVersion.parse("1.0.0"),
            loaded=ReleaseVersion.parse("1.1.0"),
            staged=ReleaseVersion.parse("1.2.0"),
            app_latest=ReleaseVersion.parse("1.1.0"),
            published_tags=frozenset({"v1.1.0"}),
        )
