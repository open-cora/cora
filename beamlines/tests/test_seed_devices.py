"""What the seeder sends, and what it refuses to decide."""

from collections.abc import Callable

import httpx
import pytest

from descriptor import DeviceEntry, DeviceRegister
from seed_devices import idempotency_key, seed

SCHEME = "epics-record"


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://keeper.example")


def test_idempotency_key_is_stable_for_one_address() -> None:
    assert idempotency_key(SCHEME, "2bmb:m1") == idempotency_key(SCHEME, "2bmb:m1")


def test_idempotency_key_differs_between_addresses() -> None:
    assert idempotency_key(SCHEME, "2bmb:m1") != idempotency_key(SCHEME, "2bmb:m10")


def test_a_dry_run_sends_no_write() -> None:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"items": [], "next_cursor": None})

    register = DeviceRegister(SCHEME, (DeviceEntry("2bmb:m1", "Sample rotation", True),))
    with _client(handler) as client:
        assert seed(client, register, dry_run=True) == 0

    assert [request.method for request in sent] == ["GET"]


def test_a_device_already_registered_is_not_registered_again() -> None:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(
            200,
            json={
                "items": [{"device_id": "9b1a3b3e-0d1f-4a5e-8f6c-2c9a1f0e7d11"}],
                "next_cursor": None,
            },
        )

    register = DeviceRegister(SCHEME, (DeviceEntry("2bmb:m1", "Sample rotation", True),))
    with _client(handler) as client:
        assert seed(client, register, dry_run=False) == 0

    assert [request.method for request in sent] == ["GET"]


def test_registering_carries_the_derived_idempotency_key() -> None:
    posted: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"items": [], "next_cursor": None})
        posted.append(request)
        return httpx.Response(201, json={"device_id": "9b1a3b3e-0d1f-4a5e-8f6c-2c9a1f0e7d11"})

    register = DeviceRegister(SCHEME, (DeviceEntry("2bmb:m1", "Sample rotation", True),))
    with _client(handler) as client:
        assert seed(client, register, dry_run=False) == 0

    assert posted[0].headers["Idempotency-Key"] == idempotency_key(SCHEME, "2bmb:m1")


def test_an_address_with_two_records_fails_rather_than_picking_one() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [
                    {"device_id": "9b1a3b3e-0d1f-4a5e-8f6c-2c9a1f0e7d11"},
                    {"device_id": "1f2e3d4c-5b6a-4798-8899-aabbccddeeff"},
                ],
                "next_cursor": None,
            },
        )

    register = DeviceRegister(SCHEME, (DeviceEntry("2bmb:m1", "Sample rotation", True),))
    with _client(handler) as client:
        assert seed(client, register, dry_run=False) == 1


@pytest.mark.parametrize("dry_run", [True, False])
def test_an_empty_register_sends_nothing(dry_run: bool) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("an empty register should not reach the network at all")

    with _client(handler) as client:
        assert seed(client, DeviceRegister(SCHEME, ()), dry_run=dry_run) == 0
