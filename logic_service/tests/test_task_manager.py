import pytest
from unittest.mock import AsyncMock

import services.Task_manager as task_module


class DummyPosManager:
    def __init__(self):
        self.unblocked = []

    async def un_block_point(self, point):
        self.unblocked.append(point)


@pytest.mark.asyncio
async def test_x_order_status_6_does_not_unlock(monkeypatch):
    task_service = task_module.TaskService()
    task_service.tracking_task["X-100"] = {"position": "P-01"}

    dummy = DummyPosManager()
    monkeypatch.setattr(task_module, "pos_manager", dummy)

    await task_service.unlock_task({
        "orderId": "X-100",
        "status": 6,
        "subTaskStatus": 2,
        "subTaskSeq": 2,
    })

    assert task_service.tracking_task["X-100"]["position"] == "P-01"
    assert dummy.unblocked == []


@pytest.mark.asyncio
async def test_x_order_status_8_unlocks_after_delay(monkeypatch):
    task_service = task_module.TaskService()
    task_service.tracking_task["X-200"] = {"position": "P-02"}

    dummy = DummyPosManager()
    monkeypatch.setattr(task_module, "pos_manager", dummy)
    sleep_mock = AsyncMock()
    monkeypatch.setattr(task_module.asyncio, "sleep", sleep_mock)

    await task_service.unlock_task({
        "orderId": "X-200",
        "status": 8,
        "subTaskStatus": 2,
        "subTaskSeq": 1,
    })

    sleep_mock.assert_awaited_once_with(30)
    assert dummy.unblocked == ["P-02"]
    assert "X-200" not in task_service.tracking_task
