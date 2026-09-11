# Copyright (C) 2026, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""
Unit tests for the Flask REST API.

Every vm_manager entry point the routes call is replaced here, so nothing
touches libvirt, Ceph or Pacemaker.

In production this module is not run directly: the vmmgrapi role of
seapath/ansible serves `app` with gunicorn on a unix socket, behind an
nginx that carries the TLS, the authentication and the ACL. main() is a
debug entry point, and since the application authenticates nobody on its
own, the address it binds to is worth pinning down in a test.

The public API keeps /stop and /start on GET, so the tests assert that
cross-site requests to them are refused before the backend is reached.
"""

import pytest

from vm_manager import vm_manager_api


@pytest.fixture
def client():
    """Return a test client for the API."""
    return vm_manager_api.app.test_client()


def test_main_binds_the_loopback(monkeypatch):
    calls = []
    monkeypatch.setattr(
        vm_manager_api.app, "run", lambda **kwargs: calls.append(kwargs)
    )

    vm_manager_api.main()

    assert calls == [{"host": "127.0.0.1"}]


def test_list_vms(client, monkeypatch):
    monkeypatch.setattr(vm_manager_api.v, "list_vms", lambda: ["vm1", "vm2"])

    response = client.get("/")

    assert response.status_code == 200
    assert response.get_json() == ["vm1", "vm2"]


def test_status(client, monkeypatch):
    monkeypatch.setattr(
        vm_manager_api.v, "status", lambda guest: f"{guest} is Running"
    )

    response = client.get("/status/guest0")

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "guest0 is Running"


def test_stop(client, monkeypatch):
    monkeypatch.setattr(
        vm_manager_api.v, "stop", lambda guest: f"{guest} stopped"
    )

    response = client.get("/stop/guest0")

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "guest0 stopped"


def test_start_reports_a_silent_success(client, monkeypatch):
    """A backend returning nothing is a success, not an empty answer."""
    monkeypatch.setattr(vm_manager_api.v, "start", lambda guest: None)

    response = client.get("/start/guest0")

    assert response.status_code == 200
    assert "should be OK" in response.get_data(as_text=True)


def test_start_reports_the_backend_error(client, monkeypatch):
    def raise_error(guest):
        raise RuntimeError(f"no such VM: {guest}")

    monkeypatch.setattr(vm_manager_api.v, "start", raise_error)

    response = client.get("/start/guest0")

    assert response.status_code == 500
    assert (
        response.get_data(as_text=True) == "RuntimeError: no such VM: guest0"
    )


@pytest.mark.parametrize("action", ["stop", "start"])
@pytest.mark.parametrize(
    "headers",
    [
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
        {"Origin": "https://evil.example"},
    ],
)
def test_cross_site_request_is_refused(client, monkeypatch, action, headers):
    def unexpected(guest):
        raise AssertionError("the backend must not run cross-site")

    monkeypatch.setattr(vm_manager_api.v, action, unexpected)

    response = client.get(f"/{action}/guest0", headers=headers)

    assert response.status_code == 403


@pytest.mark.parametrize(
    "headers",
    [
        {"Sec-Fetch-Site": "same-origin"},
        {"Origin": "http://localhost"},
        {},
    ],
)
def test_same_origin_or_non_browser_request_is_allowed(
    client, monkeypatch, headers
):
    monkeypatch.setattr(vm_manager_api.v, "stop", lambda guest: "ok")

    response = client.get("/stop/guest0", headers=headers)

    assert response.status_code == 200
