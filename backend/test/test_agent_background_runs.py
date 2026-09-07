import pytest

from app.tasks.agent_tasks import _consume_agent_run


class _FakeLoop:
    def __init__(self, events: list[str]):
        self.events = events

    async def run(self, _message: str):
        for event in self.events:
            yield event


@pytest.mark.asyncio
async def test_background_run_collects_terminal_event():
    completed, error = await _consume_agent_run(
        _FakeLoop([
            'data: {"type":"thinking","iteration":1}\n\n',
            'data: {"type":"done","success":true,"iterations":2}\n\n',
        ]),
        "summarize the job",
    )

    assert completed == {"type": "done", "success": True, "iterations": 2}
    assert error is None


@pytest.mark.asyncio
async def test_background_run_records_agent_error():
    completed, error = await _consume_agent_run(
        _FakeLoop(['data: {"type":"error","message":"provider timed out"}\n\n']),
        "summarize the job",
    )

    assert completed is None
    assert error == "provider timed out"
