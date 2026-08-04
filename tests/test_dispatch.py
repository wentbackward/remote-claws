"""Test the action dispatcher: routing, validation, permission checks."""

import json

import pytest

from remote_claws.dispatch import run_action


class _AllowAll:
    def is_action_allowed(self, group, action):
        return True


class _DenyAll:
    def is_action_allowed(self, group, action):
        return False


def _h_ping(app):
    return "pong"


def _h_greet(app, name: str):
    return f"hi {name}"


async def _h_async(app, value: str = "default"):
    return f"async:{value}"


_HANDLERS = {"ping": _h_ping, "greet": _h_greet, "async_": _h_async}


@pytest.mark.asyncio
async def test_routes_to_sync_handler():
    result = await run_action(
        group="g",
        handlers=_HANDLERS,
        action="ping",
        app=None,
        params={},
        permissions=_AllowAll(),
    )
    assert result == "pong"


@pytest.mark.asyncio
async def test_routes_to_async_handler_and_filters_params():
    result = await run_action(
        group="g",
        handlers=_HANDLERS,
        action="async_",
        app=None,
        params={"value": "x", "unrelated": "ignored"},
        permissions=_AllowAll(),
    )
    assert result == "async:x"


@pytest.mark.asyncio
async def test_unknown_action_returns_valid_list():
    result = await run_action(
        group="g",
        handlers=_HANDLERS,
        action="nope",
        app=None,
        params={},
        permissions=_AllowAll(),
    )
    data = json.loads(result)
    assert "unknown action" in data["error"]
    assert data["valid_actions"] == ["async_", "greet", "ping"]


@pytest.mark.asyncio
async def test_denied_action_returns_error_string():
    result = await run_action(
        group="browser",
        handlers=_HANDLERS,
        action="ping",
        app=None,
        params={},
        permissions=_DenyAll(),
    )
    assert json.loads(result)["error"] == "permission denied: browser:ping"


@pytest.mark.asyncio
async def test_missing_required_param_rejected():
    for bad in ({}, {"name": ""}, {"name": None}):
        result = await run_action(
            group="g",
            handlers=_HANDLERS,
            action="greet",
            app=None,
            params=bad,
            permissions=_AllowAll(),
        )
        assert "requires params: name" in json.loads(result)["error"]


@pytest.mark.asyncio
async def test_app_is_injected():
    seen = {}

    def h_capture(app):
        seen["app"] = app
        return "ok"

    await run_action(
        group="g",
        handlers={"cap": h_capture},
        action="cap",
        app="SENTINEL",
        params={},
        permissions=_AllowAll(),
    )
    assert seen["app"] == "SENTINEL"


@pytest.mark.asyncio
async def test_non_string_result_passes_through_untouched():
    sentinel = object()

    def h_obj(app):
        return sentinel

    result = await run_action(
        group="g",
        handlers={"obj": h_obj},
        action="obj",
        app=None,
        params={},
        permissions=_AllowAll(),
    )
    assert result is sentinel
