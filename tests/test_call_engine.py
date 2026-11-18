from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import noxy.core.call_engine.base as call_base
from noxy import db
from noxy.core.call import Call, call, noxy
from noxy.services.track import QueueItem


def test_public_call_imports_and_methods_are_preserved():
    assert call is noxy
    assert isinstance(call, Call)
    for name in (
        "pause_stream",
        "resume_stream",
        "stop_stream",
        "force_stop_stream",
        "stop_stream_force",
        "skip_stream",
        "seek_stream",
        "stream_call",
        "join_call",
        "speedup_stream",
        "play",
        "start",
        "stop",
        "decorators",
        "for_slot",
        "lock",
    ):
        assert callable(getattr(call, name))


def test_lock_is_reused_per_chat():
    engine = Call()
    assert engine.lock(-1001) is engine.lock(-1001)
    assert engine.lock(-1001) is not engine.lock(-1002)


@pytest.mark.asyncio
async def test_clear_resets_queue_and_chat_state(monkeypatch):
    engine = Call()
    chat_id = -100123456789
    db[chat_id] = [QueueItem(title="Test track", file="track.mp3", vidid="test")]
    engine._autoend[chat_id] = 123.0
    engine._autoplay_history[chat_id] = ["track-a"]
    engine._consecutive_failures[chat_id] = 2

    remove_video = AsyncMock()
    remove_active = AsyncMock()
    monkeypatch.setattr(call_base, "remove_active_video_chat", remove_video)
    monkeypatch.setattr(call_base, "remove_active_chat", remove_active)

    await engine._clear(chat_id)

    assert db.get(chat_id) == []
    assert chat_id not in engine._autoend
    assert chat_id not in engine._autoplay_history
    assert chat_id not in engine._consecutive_failures
    remove_video.assert_awaited_once_with(chat_id)
    remove_active.assert_awaited_once_with(chat_id)


def test_for_slot_returns_only_started_clients():
    engine = Call()
    client = object()
    engine._by_slot[2] = client

    assert engine.for_slot(2) is None

    engine._started.append(client)
    assert engine.for_slot(2) is client
