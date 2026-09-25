from pathlib import Path

from vera_core.task_wake_scheduler import TaskWakeScheduler


def test_interval_wakes_survive_restart_and_do_not_duplicate(tmp_path: Path):
    path = tmp_path / "wake.sqlite3"

    scheduler = TaskWakeScheduler(path)
    scheduler.add_interval(
        schedule_id="daily-review",
        task_id="task-1",
        every_seconds=10.0,
        first_at=5.0,
    )
    first = scheduler.tick(now=15.0)

    assert [wake.due_at for wake in first] == [5.0, 15.0]
    assert all(wake.authorization_effect == "NONE" for wake in first)

    restarted = TaskWakeScheduler(path)
    assert restarted.tick(now=15.0) == ()

    later = restarted.tick(now=25.0)
    assert [wake.due_at for wake in later] == [25.0]
    assert later[0].schedule_id == "daily-review"
    assert later[0].task_id == "task-1"
