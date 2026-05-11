"""Tests for TaskManager — CRUD, status transitions, blockedBy cascade."""

import json
import tempfile
from pathlib import Path

import pytest

from rich_senpai.core.unit.team.tasks_file import TaskManager


# ── helpers ────────────────────────────────────────────────────────────


def _make_mgr() -> tuple[TaskManager, Path]:
    tmp = Path(tempfile.mkdtemp())
    mgr = TaskManager(tasks_dir=tmp / "tasks")
    return mgr, tmp


# ── create + get ───────────────────────────────────────────────────────


def test_create_returns_json_with_id():
    mgr, _ = _make_mgr()
    result = mgr.create("fix login bug", "users cannot login with OAuth")
    task = json.loads(result)
    assert task["id"] == 1
    assert task["subject"] == "fix login bug"
    assert task["description"] == "users cannot login with OAuth"
    assert task["status"] == "pending"
    assert task["owner"] is None
    assert task["blockedBy"] == []


def test_get_existing_task():
    mgr, _ = _make_mgr()
    mgr.create("task A")
    task = json.loads(mgr.get(1))
    assert task["id"] == 1
    assert task["subject"] == "task A"


def test_get_nonexistent_task_raises():
    mgr, _ = _make_mgr()
    with pytest.raises(ValueError, match="Task 999 not found"):
        mgr.get(999)


def test_create_auto_increments_id():
    mgr, _ = _make_mgr()
    mgr.create("first")
    mgr.create("second")
    mgr.create("third")
    t2 = json.loads(mgr.get(2))
    t3 = json.loads(mgr.get(3))
    assert t2["id"] == 2
    assert t3["id"] == 3


def test_create_persists_across_instances():
    """TaskManager is file-backed; a new instance sees the same tasks."""
    with tempfile.TemporaryDirectory() as tmp:
        tasks_dir = Path(tmp) / "tasks"
        mgr1 = TaskManager(tasks_dir=tasks_dir)
        mgr1.create("persistent task")
        # New instance pointing at same dir.
        mgr2 = TaskManager(tasks_dir=tasks_dir)
        task = json.loads(mgr2.get(1))
        assert task["subject"] == "persistent task"


# ── status transitions ─────────────────────────────────────────────────


def test_update_status_pending_to_in_progress():
    mgr, _ = _make_mgr()
    mgr.create("a task")
    result = mgr.update(1, status="in_progress")
    task = json.loads(result)
    assert task["status"] == "in_progress"


def test_update_status_in_progress_to_completed():
    mgr, _ = _make_mgr()
    mgr.create("a task")
    mgr.update(1, status="in_progress")
    result = mgr.update(1, status="completed")
    task = json.loads(result)
    assert task["status"] == "completed"


def test_update_nonexistent_task_raises():
    mgr, _ = _make_mgr()
    with pytest.raises(ValueError, match="Task 42 not found"):
        mgr.update(42, status="in_progress")


# ── blockedBy ──────────────────────────────────────────────────────────


def test_add_blocked_by():
    mgr, _ = _make_mgr()
    mgr.create("dependent task")
    result = mgr.update(1, add_blocked_by=[3, 5])
    task = json.loads(result)
    assert task["blockedBy"] == [3, 5]


def test_remove_blocked_by():
    mgr, _ = _make_mgr()
    mgr.create("task", description="blocked by 2 and 4")
    mgr.update(1, add_blocked_by=[2, 4])
    result = mgr.update(1, remove_blocked_by=[4])
    task = json.loads(result)
    assert task["blockedBy"] == [2]


def test_blocked_by_deduplicated_and_sorted():
    mgr, _ = _make_mgr()
    mgr.create("task")
    mgr.update(1, add_blocked_by=[7])
    mgr.update(1, add_blocked_by=[7, 7, 8])
    task = json.loads(mgr.get(1))
    assert task["blockedBy"] == [7, 8]


def test_blocked_by_cascade_on_completion():
    """When a task is marked completed, its ID is removed from all other
    tasks' blockedBy lists."""
    mgr, _ = _make_mgr()
    mgr.create("blocker")
    mgr.create("dependent 1")
    mgr.create("dependent 2")
    mgr.update(2, add_blocked_by=[1])
    mgr.update(3, add_blocked_by=[1])
    # Complete the blocker.
    mgr.update(1, status="completed")
    t2 = json.loads(mgr.get(2))
    t3 = json.loads(mgr.get(3))
    assert t2["blockedBy"] == []
    assert t3["blockedBy"] == []


def test_blocked_by_cascade_only_affects_completed_id():
    """Completing task 1 should not affect task 2's blockedBy if it
    only references task 3."""
    mgr, _ = _make_mgr()
    mgr.create("blocker 1")
    mgr.create("blocker 3")
    mgr.create("dependent")
    mgr.update(3, add_blocked_by=[1, 2])
    # Complete blocker 1; task 2 should still block task 3.
    mgr.update(1, status="completed")
    t3 = json.loads(mgr.get(3))
    assert t3["blockedBy"] == [2]


# ── claim ──────────────────────────────────────────────────────────────


def test_claim_sets_owner_and_status():
    mgr, _ = _make_mgr()
    mgr.create("pending task")
    result = mgr.claim(1, "bob")
    assert "Claimed task #1 for bob" in result
    task = json.loads(mgr.get(1))
    assert task["owner"] == "bob"
    assert task["status"] == "in_progress"


# ── list_all ───────────────────────────────────────────────────────────


def test_list_all_empty():
    mgr, _ = _make_mgr()
    assert mgr.list_all() == "No tasks."


def test_list_all_shows_tasks_with_glyphs():
    mgr, _ = _make_mgr()
    mgr.create("pending")
    mgr.create("in progress task")
    mgr.update(2, status="in_progress")
    out = mgr.list_all()
    assert "[ ] #1: pending" in out
    assert "[>] #2: in progress task" in out


def test_list_all_shows_owner_and_blocked():
    mgr, _ = _make_mgr()
    mgr.create("busy task")
    mgr.claim(1, "alice")
    mgr.create("blocked task")
    mgr.update(2, add_blocked_by=[1])
    out = mgr.list_all()
    assert "@alice" in out
    assert "blocked by: [1]" in out


# ── list_unclaimed ─────────────────────────────────────────────────────


def test_list_unclaimed_returns_only_available_tasks():
    mgr, _ = _make_mgr()
    mgr.create("available")
    mgr.create("claimed")
    mgr.claim(2, "bob")
    mgr.create("blocked")
    mgr.update(3, add_blocked_by=[1])
    unclaimed = mgr.list_unclaimed()
    assert len(unclaimed) == 1
    assert unclaimed[0]["subject"] == "available"


def test_list_unclaimed_excludes_completed():
    mgr, _ = _make_mgr()
    mgr.create("done")
    mgr.update(1, status="completed")
    assert mgr.list_unclaimed() == []


# ── delete ─────────────────────────────────────────────────────────────


def test_delete_removes_task_file():
    mgr, tmp = _make_mgr()
    mgr.create("ephemeral")
    path = mgr._path(1)
    assert path.exists()
    result = mgr.update(1, status="deleted")
    assert "Task 1 deleted" in result
    assert not path.exists()


def test_delete_nonexistent_task_still_fails_load():
    mgr, _ = _make_mgr()
    with pytest.raises(ValueError, match="Task 99 not found"):
        mgr.update(99, status="deleted")


# ── tasks_dir creation ─────────────────────────────────────────────────


def test_tasks_dir_created_on_init():
    with tempfile.TemporaryDirectory() as tmp:
        tasks = Path(tmp) / "nested" / "tasks"
        mgr = TaskManager(tasks_dir=tasks)
        assert tasks.is_dir()
