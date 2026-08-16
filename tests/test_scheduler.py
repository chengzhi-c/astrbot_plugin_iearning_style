"""Scheduler configuration tests."""

from learning_style.scheduler import Scheduler


def test_invalid_intervals_fall_back_to_defaults():
    scheduler = Scheduler(
        data_manager=object(),
        learning_manager=object(),
        config={
            "analysis_interval_seconds": 0,
            "maintenance_interval_seconds": -1,
        },
    )

    assert scheduler.analysis_interval == 3600
    assert scheduler.maintenance_interval == 86400
