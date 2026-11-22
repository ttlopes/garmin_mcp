"""
Integration tests for the lifestyle logging tools in health_wellness.

The request shapes asserted here were captured from the Garmin Connect iOS
app (5.31) talking to connectapi.garmin.com/lifestylelogging-service.
"""
import copy
import json
from unittest.mock import Mock

import pytest
from garminconnect import GarminConnectConnectionError
from mcp.server.fastmcp import FastMCP

from garmin_mcp import health_wellness
from tests.fixtures.garmin_responses import MOCK_LIFESTYLE_LOGGING_DATA

PROFILE_PK = 4242

BEHAVIORS = [
    {
        "behaviourId": 1, "userProfilePk": None, "measurementType": "QUANTITY",
        "name": "Alcohol", "hidden": False, "category": "LIFESTYLE",
        "subTypes": [
            {"subTypeId": 1, "name": "BEER"}, {"subTypeId": 2, "name": "WINE"},
            {"subTypeId": 3, "name": "SPIRIT"}, {"subTypeId": 4, "name": "OTHER"},
        ],
        "sequenceOrder": 1, "sleepRelated": False, "tracked": True, "autoLoggable": False,
    },
    {
        "behaviourId": 3, "userProfilePk": None, "measurementType": "NONE",
        "name": "Light Exercise", "hidden": False, "category": "LIFESTYLE", "subTypes": [],
        "sequenceOrder": 4, "sleepRelated": False, "tracked": True, "autoLoggable": True,
    },
    {
        "behaviourId": 7, "userProfilePk": None, "measurementType": "NONE",
        "name": "Cold Showers/Baths", "hidden": False, "category": "SELF_CARE", "subTypes": [],
        "sequenceOrder": 9, "sleepRelated": False, "tracked": False, "autoLoggable": False,
    },
    {
        "behaviourId": 1000, "userProfilePk": PROFILE_PK, "measurementType": "QUANTITY",
        "name": "Midday Caffeine", "hidden": False, "subTypes": None, "category": "CUSTOM",
        "sleepRelated": False, "tracked": True, "autoLoggable": False,
    },
    {
        "behaviourId": 1001, "userProfilePk": PROFILE_PK, "measurementType": "NONE",
        "name": "Breakfast", "hidden": False, "subTypes": None, "category": "CUSTOM",
        "sleepRelated": False, "tracked": True, "autoLoggable": False,
    },
    {
        "behaviourId": 1002, "userProfilePk": PROFILE_PK, "measurementType": "NONE",
        "name": "TV before bed", "hidden": False, "subTypes": None,
        "category": "CUSTOM_SLEEP_RELATED", "sleepRelated": True, "tracked": True,
        "autoLoggable": False,
    },
]
TRACKED_IDS = [1, 3, 1000, 1001, 1002]


def _connectapi(path, **kwargs):
    if path.startswith("/lifestylelogging-service/behaviours/"):
        return copy.deepcopy(BEHAVIORS)
    if path.startswith("/lifestylelogging-service/dailyLog/"):
        return copy.deepcopy(MOCK_LIFESTYLE_LOGGING_DATA)
    if path == "/userpreference-service/lifestyle.auto-logging.enabled":
        return {"key": "lifestyle.auto-logging.enabled", "value": "true"}
    raise AssertionError(f"unexpected GET {path}")


@pytest.fixture
def client():
    client = Mock()
    client.connectapi = Mock(side_effect=_connectapi)
    client.client = Mock()
    client.client.put = Mock(return_value=None)
    client.client.post = Mock(return_value=None)
    client.client.delete = Mock(return_value=None)
    return client


@pytest.fixture
def app(client):
    health_wellness.configure(client)
    return health_wellness.register_tools(FastMCP("Test Lifestyle Logging"))


async def _call(app, name, args):
    result = await app.call_tool(name, args)
    return result[0][0].text


async def _call_json(app, name, args):
    return json.loads(await _call(app, name, args))


def _sent(mock_call):
    """(path, json payload) of a recorded client.put/post/delete call."""
    args, kwargs = mock_call
    return args[1], kwargs.get("json")


# --- get_lifestyle_behaviors -------------------------------------------------

@pytest.mark.asyncio
async def test_get_lifestyle_behaviors_summarizes_and_reports_auto_logging(app, client):
    data = await _call_json(app, "get_lifestyle_behaviors", {"date": "2024-01-15"})

    client.connectapi.assert_any_call("/lifestylelogging-service/behaviours/2024-01-15")
    assert data["date"] == "2024-01-15"
    assert data["auto_logging_enabled"] is True
    alcohol = data["behaviors"][0]
    assert alcohol == {
        "id": 1, "name": "Alcohol", "category": "LIFESTYLE", "measurement_type": "QUANTITY",
        "sub_types": ["BEER", "WINE", "SPIRIT", "OTHER"], "tracked": True, "custom": False,
        "sleep_related": False, "auto_loggable": False,
    }
    assert [b["custom"] for b in data["behaviors"]][-3:] == [True, True, True]


@pytest.mark.asyncio
async def test_get_lifestyle_behaviors_tracked_only(app):
    data = await _call_json(app, "get_lifestyle_behaviors", {"date": "2024-01-15", "tracked_only": True})
    assert [b["id"] for b in data["behaviors"]] == TRACKED_IDS


@pytest.mark.asyncio
async def test_get_lifestyle_behaviors_auto_logging_failure_is_null(app, client):
    def connectapi(path, **kwargs):
        if "userpreference" in path:
            raise Exception("preference down")
        return _connectapi(path, **kwargs)

    client.connectapi.side_effect = connectapi
    data = await _call_json(app, "get_lifestyle_behaviors", {"date": "2024-01-15"})
    assert data["auto_logging_enabled"] is None
    assert len(data["behaviors"]) == len(BEHAVIORS)


@pytest.mark.asyncio
async def test_get_lifestyle_behaviors_error(app, client):
    client.connectapi.side_effect = Exception("API Error")
    result = await _call(app, "get_lifestyle_behaviors", {"date": "2024-01-15"})
    assert "Error retrieving lifestyle behaviors" in result


@pytest.mark.asyncio
async def test_get_lifestyle_behaviors_rejects_bad_date(app, client):
    result = await _call(app, "get_lifestyle_behaviors", {"date": "15/01/2024"})
    assert "YYYY-MM-DD" in result
    client.connectapi.assert_not_called()


# --- log_lifestyle_behavior ----------------------------------------------------

@pytest.mark.asyncio
async def test_log_yes_no_behavior(app, client):
    data = await _call_json(app, "log_lifestyle_behavior", {"date": "2024-01-15", "behavior_id": 1001})

    path, payload = _sent(client.client.put.call_args)
    assert path == "/lifestylelogging-service/dailyLog/1001/2024-01-15"
    assert payload["logStatus"] == "YES"
    assert "details" not in payload
    assert payload["updateTimestamp"][:4].isdigit() and "T" in payload["updateTimestamp"]
    assert data == {
        "status": "success", "date": "2024-01-15", "behavior_id": 1001,
        "behavior": "Breakfast", "logged": "YES",
    }


@pytest.mark.asyncio
async def test_log_explicit_no(app, client):
    data = await _call_json(
        app, "log_lifestyle_behavior", {"date": "2024-01-15", "behavior_id": 1, "logged": False}
    )
    _, payload = _sent(client.client.put.call_args)
    assert payload["logStatus"] == "NO"
    assert "details" not in payload
    assert data["logged"] == "NO"


@pytest.mark.asyncio
async def test_log_quantity_without_sub_types(app, client):
    data = await _call_json(
        app, "log_lifestyle_behavior", {"date": "2024-01-15", "behavior_id": 1000, "amount": 3}
    )
    _, payload = _sent(client.client.put.call_args)
    assert payload["logStatus"] == "YES"
    assert payload["details"] == [{"amount": 3}]
    assert data["amounts"] == [{"amount": 3}]


@pytest.mark.asyncio
async def test_log_quantity_with_sub_types(app, client):
    data = await _call_json(app, "log_lifestyle_behavior", {
        "date": "2024-01-15", "behavior_id": 1,
        "sub_type_amounts": {"beer": 2, "Spirit": 1},
    })
    path, payload = _sent(client.client.put.call_args)
    assert path == "/lifestylelogging-service/dailyLog/1/2024-01-15"
    assert payload["details"] == [
        {"subTypeId": 1, "subTypeName": "", "amount": 2},
        {"subTypeId": 3, "subTypeName": "", "amount": 1},
    ]
    assert data["amounts"] == [
        {"sub_type": "BEER", "amount": 2}, {"sub_type": "SPIRIT", "amount": 1},
    ]


@pytest.mark.parametrize("args, message", [
    ({"behavior_id": 1001, "amount": 2}, "yes/no behavior"),
    ({"behavior_id": 1, "logged": False, "sub_type_amounts": {"BEER": 1}}, "logged=false"),
    ({"behavior_id": 1000}, "amount is required"),
    ({"behavior_id": 1000, "amount": 26}, "between 1 and 25"),
    ({"behavior_id": 1000, "amount": 0}, "between 1 and 25"),
    ({"behavior_id": 1000, "sub_type_amounts": {"BEER": 1}}, "no sub-types"),
    ({"behavior_id": 1, "amount": 2}, "counted per sub-type"),
    ({"behavior_id": 1}, "sub_type_amounts is required"),
    ({"behavior_id": 1, "sub_type_amounts": {"CIDER": 1}}, "Unknown sub-type"),
    ({"behavior_id": 999}, "No lifestyle behavior with id 999"),
])
@pytest.mark.asyncio
async def test_log_rejects_invalid_input_without_writing(app, client, args, message):
    data = await _call_json(app, "log_lifestyle_behavior", {"date": "2024-01-15", **args})
    assert data["status"] == "error"
    assert message in data["message"]
    assert data["write_committed"] is False
    client.client.put.assert_not_called()


@pytest.mark.asyncio
async def test_log_reports_garmin_rejection(app, client):
    client.client.put.side_effect = GarminConnectConnectionError("API Error 400 - Bad Request")
    data = await _call_json(app, "log_lifestyle_behavior", {"date": "2024-01-15", "behavior_id": 1001})
    assert data["status"] == "error"
    assert data["upstream_status"] == 400
    assert data["write_committed"] is False


# --- clear_lifestyle_behavior_log -------------------------------------------

@pytest.mark.asyncio
async def test_clear_previews_logged_entry(app, client):
    data = await _call_json(app, "clear_lifestyle_behavior_log", {"date": "2024-01-15", "behavior_id": 1})
    assert data["status"] == "needs_confirmation"
    assert data["entry"]["logStatus"] == "YES"
    client.connectapi.assert_any_call(
        "/lifestylelogging-service/dailyLog/2024-01-15", params={"showSubtypes": "true"}
    )
    client.client.delete.assert_not_called()


@pytest.mark.asyncio
async def test_clear_preview_when_nothing_logged(app, client):
    data = await _call_json(app, "clear_lifestyle_behavior_log", {"date": "2024-01-15", "behavior_id": 35})
    assert data["status"] == "nothing_logged"
    client.client.delete.assert_not_called()


@pytest.mark.asyncio
async def test_clear_confirmed_deletes_entry(app, client):
    data = await _call_json(
        app, "clear_lifestyle_behavior_log",
        {"date": "2024-01-15", "behavior_id": 1, "confirm": True},
    )
    path, _ = _sent(client.client.delete.call_args)
    assert path == "/lifestylelogging-service/dailyLog/1/2024-01-15"
    assert data["status"] == "success"


@pytest.mark.asyncio
async def test_clear_error_after_send_is_unknown(app, client):
    client.client.delete.side_effect = GarminConnectConnectionError("API Error 502 - Bad Gateway")
    data = await _call_json(
        app, "clear_lifestyle_behavior_log",
        {"date": "2024-01-15", "behavior_id": 1, "confirm": True},
    )
    assert data["write_committed"] == "unknown"


# --- create_lifestyle_behaviors ----------------------------------------------

def _created(payload):
    return [
        {
            "behaviourId": 2000 + i, "userProfilePk": PROFILE_PK,
            "measurementType": item["measurementType"], "name": item["name"], "hidden": False,
            "subTypes": None,
            "category": "CUSTOM_SLEEP_RELATED" if item["sleepRelated"] else "CUSTOM",
            "tracked": False, "autoLoggable": False, "sleepRelated": item["sleepRelated"],
        }
        for i, item in enumerate(payload)
    ]


@pytest.mark.asyncio
async def test_create_behaviors_and_track_them(app, client):
    client.client.post.side_effect = lambda *a, **kw: _created(kw["json"])
    data = await _call_json(app, "create_lifestyle_behaviors", {"behaviors": [
        {"name": " Creatine ", "measurement_type": "none"},
        {"name": "Water glasses", "measurement_type": "QUANTITY", "sleep_related": True},
    ]})

    path, payload = _sent(client.client.post.call_args)
    assert path == "/lifestylelogging-service/behaviours/batch"
    assert payload == [
        {"name": "Creatine", "measurementType": "NONE", "sleepRelated": False},
        {"name": "Water glasses", "measurementType": "QUANTITY", "sleepRelated": True},
    ]
    path, tracked = _sent(client.client.put.call_args)
    assert path == "/lifestylelogging-service/trackedBehaviours"
    assert tracked["trackedBehaviours"] == TRACKED_IDS + [2000, 2001]
    assert tracked["userProfilePk"] == PROFILE_PK
    assert data["status"] == "success"
    assert [b["tracked"] for b in data["created"]] == [True, True]
    assert data["created"][1]["category"] == "CUSTOM_SLEEP_RELATED"


@pytest.mark.asyncio
async def test_create_without_tracking(app, client):
    client.client.post.side_effect = lambda *a, **kw: _created(kw["json"])
    data = await _call_json(
        app, "create_lifestyle_behaviors", {"behaviors": [{"name": "Stretch"}], "track": False}
    )
    client.client.put.assert_not_called()
    assert data["created"][0]["tracked"] is False


@pytest.mark.parametrize("behaviors, message", [
    ([], "non-empty list"),
    ([{"name": "breakfast"}], "already exists"),
    ([{"name": "A"}, {"name": "a"}], "already exists"),
    ([{"name": "  "}], "non-empty string"),
    ([{"name": "X", "measurement_type": "SCALE"}], "measurement_type"),
    ([{"name": "X", "sleep_related": "yes"}], "sleep_related"),
])
@pytest.mark.asyncio
async def test_create_rejects_invalid_input(app, client, behaviors, message):
    data = await _call_json(app, "create_lifestyle_behaviors", {"behaviors": behaviors})
    assert data["status"] == "error"
    assert message in data["message"]
    assert data["write_committed"] is False
    client.client.post.assert_not_called()


@pytest.mark.asyncio
async def test_create_reports_partial_when_tracking_fails(app, client):
    client.client.post.side_effect = lambda *a, **kw: _created(kw["json"])
    client.client.put.side_effect = GarminConnectConnectionError("API Error 500 - oops")
    data = await _call_json(app, "create_lifestyle_behaviors", {"behaviors": [{"name": "Stretch"}]})
    assert data["status"] == "partial"
    assert "set_tracked_lifestyle_behaviors" in data["hint"]
    assert data["created"][0]["id"] == 2000


# --- update_lifestyle_behavior -------------------------------------------------

@pytest.mark.asyncio
async def test_update_renames_and_keeps_other_fields(app, client):
    client.client.put.side_effect = lambda *a, **kw: {
        **BEHAVIORS[4], **kw["json"], "tracked": False,
    }
    data = await _call_json(app, "update_lifestyle_behavior", {"behavior_id": 1001, "name": "Big breakfast"})

    path, payload = _sent(client.client.put.call_args)
    assert path == "/lifestylelogging-service/behaviours/1001"
    assert payload == {"measurementType": "NONE", "name": "Big breakfast", "sleepRelated": False}
    assert data["behavior"]["name"] == "Big breakfast"
    assert data["behavior"]["tracked"] is True  # not the response's stale false


@pytest.mark.parametrize("args, message", [
    ({"behavior_id": 1001}, "at least one"),
    ({"behavior_id": 1, "name": "Booze"}, "built-in"),
    ({"behavior_id": 1001, "name": "Midday caffeine"}, "already exists"),
    ({"behavior_id": 1001, "measurement_type": "LIST"}, "measurement_type"),
])
@pytest.mark.asyncio
async def test_update_rejects_invalid_input(app, client, args, message):
    data = await _call_json(app, "update_lifestyle_behavior", args)
    assert message in data["message"]
    client.client.put.assert_not_called()


@pytest.mark.asyncio
async def test_update_allows_keeping_its_own_name(app, client):
    client.client.put.side_effect = lambda *a, **kw: {**BEHAVIORS[4], **kw["json"]}
    data = await _call_json(
        app, "update_lifestyle_behavior", {"behavior_id": 1001, "name": "Breakfast", "sleep_related": True}
    )
    assert data["status"] == "success"
    _, payload = _sent(client.client.put.call_args)
    assert payload["sleepRelated"] is True


# --- delete_lifestyle_behaviors ------------------------------------------------

@pytest.mark.asyncio
async def test_delete_previews_by_default(app, client):
    data = await _call_json(app, "delete_lifestyle_behaviors", {"behavior_ids": [1001, 1002]})
    assert data["status"] == "needs_confirmation"
    assert [b["name"] for b in data["behaviors"]] == ["Breakfast", "TV before bed"]
    client.client.delete.assert_not_called()


@pytest.mark.asyncio
async def test_delete_confirmed_removes_and_untracks(app, client):
    data = await _call_json(
        app, "delete_lifestyle_behaviors", {"behavior_ids": [1001, 1001, 1002], "confirm": True}
    )
    path, payload = _sent(client.client.delete.call_args)
    assert path == "/lifestylelogging-service/behaviours/batchDelete"
    assert payload == {"ids": [1001, 1002]}
    _, tracked = _sent(client.client.put.call_args)
    assert tracked["trackedBehaviours"] == [1, 3, 1000]
    assert data["status"] == "success"
    assert data["deleted"] == [{"id": 1001, "name": "Breakfast"}, {"id": 1002, "name": "TV before bed"}]


@pytest.mark.asyncio
async def test_delete_rejects_built_in(app, client):
    data = await _call_json(
        app, "delete_lifestyle_behaviors", {"behavior_ids": [1, 1001], "confirm": True}
    )
    assert "Built-in behaviors cannot be deleted: Alcohol" in data["message"]
    client.client.delete.assert_not_called()


# --- set_tracked_lifestyle_behaviors -----------------------------------------

@pytest.mark.asyncio
async def test_set_tracked_reports_changes(app, client):
    client.client.put.side_effect = lambda *a, **kw: {
        "userProfilePk": PROFILE_PK, "calendarDate": kw["json"]["calendarDate"],
        "trackedBehaviours": kw["json"]["trackedBehaviours"],
    }
    data = await _call_json(
        app, "set_tracked_lifestyle_behaviors",
        {"behavior_ids": [3, 1, 7, 1000, 1001, 1002], "date": "2024-01-15"},
    )
    path, payload = _sent(client.client.put.call_args)
    assert path == "/lifestylelogging-service/trackedBehaviours"
    assert payload == {
        "trackedBehaviours": [3, 1, 7, 1000, 1001, 1002],
        "calendarDate": "2024-01-15", "userProfilePk": PROFILE_PK,
    }
    assert data["added"] == [{"id": 7, "name": "Cold Showers/Baths"}]
    assert data["removed"] == []
    assert [t["id"] for t in data["tracked"]] == [3, 1, 7, 1000, 1001, 1002]


@pytest.mark.asyncio
async def test_set_tracked_rejects_unknown_ids(app, client):
    data = await _call_json(app, "set_tracked_lifestyle_behaviors", {"behavior_ids": [1, 555]})
    assert "Unknown behavior ids [555]" in data["message"]
    client.client.put.assert_not_called()


@pytest.mark.asyncio
async def test_set_tracked_falls_back_to_social_profile_id(app, client):
    built_in_only = [b for b in BEHAVIORS if b["userProfilePk"] is None]

    def connectapi(path, **kwargs):
        if path.startswith("/lifestylelogging-service/behaviours/"):
            return copy.deepcopy(built_in_only)
        if path == "/userprofile-service/socialProfile":
            return {"profileId": 777}
        return _connectapi(path, **kwargs)

    client.connectapi.side_effect = connectapi
    await _call_json(app, "set_tracked_lifestyle_behaviors", {"behavior_ids": [1, 3]})
    _, payload = _sent(client.client.put.call_args)
    assert payload["userProfilePk"] == 777


# --- set_lifestyle_auto_logging ------------------------------------------------

@pytest.mark.parametrize("enabled, value", [(True, "true"), (False, "false")])
@pytest.mark.asyncio
async def test_set_auto_logging(app, client, enabled, value):
    client.client.put.side_effect = lambda *a, **kw: kw["json"]
    data = await _call_json(app, "set_lifestyle_auto_logging", {"enabled": enabled})
    path, payload = _sent(client.client.put.call_args)
    assert path == "/userpreference-service/lifestyle.auto-logging.enabled"
    assert payload == {"key": "lifestyle.auto-logging.enabled", "value": value}
    assert data == {"status": "success", "auto_logging_enabled": enabled}


@pytest.mark.asyncio
async def test_set_auto_logging_error(app, client):
    client.client.put.side_effect = GarminConnectConnectionError("API Error 403 - Forbidden")
    data = await _call_json(app, "set_lifestyle_auto_logging", {"enabled": False})
    assert data["status"] == "error"
    assert data["upstream_status"] == 403
