"""Ingestion / backfill tests.

Two kinds of test live here:

1. Characterization tests (no marker) that PASS against the code as it is today.
   They lock in behaviour that already works, so a future refactor can't silently
   regress it.

2. Robustness spec tests marked ``xfail(strict=True)``. These assert the
   behaviour the backlog says we WANT (retry/backoff, FailedEntryCount handling,
   batching, 256 KB guard). They fail against the current code, so they record
   as xfail and keep CI green. When someone implements the fix the test starts
   passing, strict-xfail turns that into a failure, and that is the signal to
   drop the marker and the backlog item.
"""
import json
from datetime import datetime

import pytest
from botocore.exceptions import ClientError

THROTTLE = ClientError(
    {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
    "DescribeEvents",
)
ACCESS_DENIED = ClientError(
    {"Error": {"Code": "AccessDeniedException", "Message": "nope"}},
    "DescribeEvents",
)


# --------------------------------------------------------------------------
# Characterization: single-account backfill (works today)
# --------------------------------------------------------------------------

def test_get_events_accumulates_pages(backfill_single):
    mod, clients = backfill_single
    clients["health"].describe_events.side_effect = [
        {"events": [{"arn": "1"}, {"arn": "2"}], "nextToken": "tok1"},
        {"events": [{"arn": "3"}]},
    ]
    events = mod.get_events()
    assert [e["arn"] for e in events] == ["1", "2", "3"]


def test_get_event_data_formats_times_as_gmt(backfill_single):
    mod, _ = backfill_single
    details = {
        "arn": "arn:x",
        "region": "us-east-1",
        "eventTypeCode": "AWS_EC2_OPERATIONAL_ISSUE",
        "startTime": datetime(2024, 1, 2, 3, 4, 5),
        "endTime": datetime(2024, 1, 2, 4, 4, 5),
        "lastUpdatedTime": datetime(2024, 1, 2, 3, 30, 5),
    }
    out = mod.get_event_data(details, {"latestDescription": "hello"}, {"m": 1})
    assert out["eventArn"] == "arn:x"
    assert out["startTime"] == "Tue, 02 Jan 2024 03:04:05 GMT"
    assert out["endTime"] == "Tue, 02 Jan 2024 04:04:05 GMT"
    assert out["eventDescription"] == [{"latestDescription": "hello"}]
    assert out["eventMetadata"] == {"m": 1}


def test_send_event_builds_correct_entry(backfill_single):
    mod, clients = backfill_single
    mod.send_event_defaultBus({"eventArn": "a", "x": 1}, "arn:bus")
    clients["events"].put_events.assert_called_once()
    entry = clients["events"].put_events.call_args.kwargs["Entries"][0]
    assert entry["Source"] == "heidi.health"
    assert entry["DetailType"] == "awshealthtest"
    assert entry["EventBusName"] == "arn:bus"
    assert json.loads(entry["Detail"])["eventArn"] == "a"


# --------------------------------------------------------------------------
# Characterization: org backfill (works today)
# --------------------------------------------------------------------------

def test_org_affected_accounts_paginate(backfill_org):
    mod, clients = backfill_org
    clients["health"].describe_affected_accounts_for_organization.side_effect = [
        {"affectedAccounts": ["1", "2"], "nextToken": "t"},
        {"affectedAccounts": ["3"]},
    ]
    assert mod.describe_affected_accounts({"arn": "a"}) == ["1", "2", "3"]


def test_org_event_data_account_gating(backfill_org):
    mod, _ = backfill_org
    details = {
        "arn": "arn:x",
        "startTime": datetime(2024, 1, 2, 3, 4, 5),
    }
    desc = {"latestDescription": "d"}
    without = mod.get_event_data(details, desc, {}, [], None)
    assert "affectedAccount" not in without
    withacct = mod.get_event_data(details, desc, {}, [{"entityValue": "e", "status": "s"}], "123456789012")
    assert withacct["affectedAccount"] == "123456789012"
    assert withacct["affectedEntities"] == [{"entityValue": "e", "status": "s"}]


# --------------------------------------------------------------------------
# Robustness specs (xfail until implemented) -- backlog: Ingestion robustness
# --------------------------------------------------------------------------

@pytest.mark.xfail(strict=True, reason="backlog: no retry/backoff on Health API throttling")
def test_get_events_retries_on_throttling(backfill_single):
    mod, clients = backfill_single
    clients["health"].describe_events.side_effect = [THROTTLE, {"events": [{"arn": "1"}]}]
    events = mod.get_events()
    assert [e["arn"] for e in events] == ["1"]  # should retry past the throttle


@pytest.mark.xfail(strict=True, reason="backlog: API exception treated as end-of-data (silent early stop)")
def test_get_events_does_not_silently_swallow_errors(backfill_single):
    mod, clients = backfill_single
    clients["health"].describe_events.side_effect = ACCESS_DENIED
    with pytest.raises(ClientError):
        mod.get_events()  # a non-throttle error must surface, not return []


@pytest.mark.xfail(strict=True, reason="backlog: put_events FailedEntryCount never checked")
def test_send_event_detects_failed_entries(backfill_single):
    mod, clients = backfill_single
    clients["events"].put_events.return_value = {
        "FailedEntryCount": 1,
        "Entries": [{"ErrorCode": "ThrottlingException", "ErrorMessage": "x"}],
    }
    with pytest.raises(Exception):
        mod.send_event_defaultBus({"eventArn": "a"}, "arn:bus")


@pytest.mark.xfail(strict=True, reason="backlog: org put_events FailedEntryCount never checked")
def test_org_send_event_detects_failed_entries(backfill_org):
    mod, clients = backfill_org
    clients["events"].put_events.return_value = {
        "FailedEntryCount": 1,
        "Entries": [{"ErrorCode": "InternalFailure", "ErrorMessage": "x"}],
    }
    with pytest.raises(Exception):
        mod.send_event_to_eventbridge({"eventArn": "a"}, "arn:bus")


@pytest.mark.xfail(strict=True, reason="backlog: events sent one-at-a-time, not batched up to 10")
def test_batch_send_helper_exists(backfill_single):
    mod, _ = backfill_single
    assert hasattr(mod, "send_events_batch"), "expected a PutEvents batching helper (<=10 entries)"


@pytest.mark.xfail(strict=True, reason="backlog: no handling for the 256 KB EventBridge entry limit")
def test_oversized_event_is_guarded(backfill_single):
    mod, clients = backfill_single
    oversized = {"eventArn": "a", "blob": "x" * 300_000}
    mod.send_event_defaultBus(oversized, "arn:bus")
    assert not clients["events"].put_events.called, "a >256 KB entry must not be blindly put_events'd"
