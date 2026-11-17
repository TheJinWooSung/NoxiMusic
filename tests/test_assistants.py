from __future__ import annotations

from types import SimpleNamespace

import pytest

import noxy.core.assistants as assistants_module
from noxy.database import models
from noxy.database.models import _call_for, group_assistant


@pytest.fixture()
def fake_assistants(monkeypatch, clean_cache):
    registry = {
        2: SimpleNamespace(id=200, username="two", mention="@two"),
        4: SimpleNamespace(id=400, username="four", mention="@four"),
    }
    monkeypatch.setattr(assistants_module, "assistants", registry, raising=False)

    class FakeCall:
        def __init__(self, slot: int) -> None:
            self.slot = slot

        async def play(self, chat_id, stream):
            return None

        def for_slot(self, slot: int):
            return registry.get(slot) and f"call-{slot}"

    monkeypatch.setattr(models, "_call_for", lambda assistant: f"call-{assistant}")
    yield registry


@pytest.mark.asyncio
async def test_group_assistant_resolves_existing_slot(fake_assistants):
    from noxy.database import assistant_map

    assistant_map.set(-500, 4)
    assert await group_assistant(object(), -500) == "call-4"


@pytest.mark.asyncio
async def test_group_assistant_reassigns_when_slot_is_missing(fake_assistants, monkeypatch):
    from noxy.database import assistant_map

    assistant_map.set(-501, 3)

    async def fake_lookup(*args, **kwargs):
        return None

    async def fake_set_assistant(chat_id, number=None):
        assistant_map.set(chat_id, 2)
        return None

    monkeypatch.setattr(models, "assdb", SimpleNamespace(find_one=fake_lookup))
    monkeypatch.setattr(models, "set_assistant", fake_set_assistant)

    assert await group_assistant(object(), -501) == "call-2"


def test_call_for_returns_none_for_missing_slot():
    assert _call_for(None) is None
