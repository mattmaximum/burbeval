"""A fake OpenAI-compatible async client for tests -- no network, no API
key. Adapted from reloeval's tests/fakes.py, trimmed to just the
response_format json_schema + web plugin request shape llm_fetch.py uses
(burbeval has no forced tool_choice call, unlike reloeval's normalize_city)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class FakeMessage:
    content: Optional[str] = None


@dataclass
class FakeChoice:
    message: FakeMessage


@dataclass
class FakeChatCompletion:
    choices: list


@dataclass
class FakeChatCompletions:
    handler: Callable[[dict], Optional[dict]]

    async def create(self, **kwargs):
        result = self.handler(kwargs)
        if result is None:
            raise RuntimeError("simulated API failure")
        return FakeChatCompletion(choices=[FakeChoice(message=FakeMessage(content=json.dumps(result)))])


@dataclass
class FakeChat:
    handler: Callable[[dict], Optional[dict]]

    def __post_init__(self):
        self.completions = FakeChatCompletions(handler=self.handler)


@dataclass
class FakeAsyncOpenAI:
    """handler(call_kwargs) -> dict to return, or None to simulate a total
    API failure for that call."""
    handler: Callable[[dict], Optional[dict]]

    def __post_init__(self):
        self.chat = FakeChat(handler=self.handler)
