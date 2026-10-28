"""Test harness for the HEIDI ingestion/backfill scripts.

These scripts (src/Setup/utils/HealthEventBackFill*.py) are CLI tools: they call
input() and create boto3 clients at module scope, and the single-account one
calls backfill() at import with no __main__ guard. To unit-test their functions
without network or prompts, we exec each module with input() and boto3.client
patched, capturing the mock clients so tests can drive them.
"""
import builtins
import pathlib
import types
from unittest import mock

import pytest

UTILS = pathlib.Path(__file__).resolve().parents[1] / "src" / "Setup" / "utils"


def load_script(script_name):
    """Exec a utils script under mocked input()/boto3 and return (module, clients).

    clients is {service_name: MagicMock} for every boto3.client(service, ...)
    the module created. Mock call history is reset before returning so tests
    start from a clean slate (any import-time calls are discarded), while
    return_value/side_effect configured later by tests still apply.
    """
    path = UTILS / script_name
    src = path.read_text()
    clients = {}

    def fake_client(service, *args, **kwargs):
        m = clients.get(service)
        if m is None:
            m = mock.MagicMock(name=f"{service}_client")
            clients[service] = m
        return m

    module = types.ModuleType(path.stem)
    module.__file__ = str(path)

    with mock.patch.object(builtins, "input", lambda *a, **k: ""), \
            mock.patch("boto3.client", side_effect=fake_client):
        exec(compile(src, str(path), "exec"), module.__dict__)

    for m in clients.values():
        m.reset_mock()  # discard import-time calls; keep return_value/side_effect
    return module, clients


def read_source(script_name):
    return (UTILS / script_name).read_text()


@pytest.fixture
def backfill_single():
    return load_script("HealthEventBackFill.py")


@pytest.fixture
def backfill_org():
    return load_script("HealthEventBackFillOrg.py")
