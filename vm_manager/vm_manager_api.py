#!/usr/bin/env python3
# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""Flask REST API for the vm_manager backends.

Routes are thin wrappers around the public ``vm_manager`` functions.

This application authenticates nobody and has no CSRF token flow. In
production it is imported by the wsgi.py of the vmmgrapi Ansible role,
served by gunicorn on a unix socket, and only reachable through an nginx
that terminates TLS and enforces the basic auth and the ACL. It must
never be published directly.

The public API (``GET /stop/<guest>``, ``GET /start/<guest>``) must not
change, so the state-changing routes stay on GET. A browser can issue a
cross-site GET or form POST without any preflight, and may attach cached
basic auth credentials, so a before_request hook rejects cross-site
requests to those routes, using the Fetch-Metadata ``Sec-Fetch-Site``
header and the ``Origin`` header. Clients that send neither (curl,
scripts) are not browsers and are allowed through.
"""

from urllib.parse import urlsplit

from flask import Flask, request
import vm_manager as v

app = Flask(__name__)

STATE_CHANGING_ENDPOINTS = ("stop_vm", "start_vm")


@app.before_request
def reject_cross_site_posts():
    """Refuse state-changing requests that a browser sends cross-site."""
    if request.endpoint not in STATE_CHANGING_ENDPOINTS:
        return None
    site = request.headers.get("Sec-Fetch-Site")
    if site is not None and site not in ("same-origin", "none"):
        return "Cross-site request refused", 403
    origin = request.headers.get("Origin")
    if origin is not None and urlsplit(origin).netloc != request.host:
        return "Cross-site request refused", 403
    return None


def execfunc(func, guest):
    try:
        out = func(guest)
    except Exception as err:
        return f"{err.__class__.__name__}: {err}", 500
    if not out:
        out = "vm_manager did not return anything, should be OK"
    return out


@app.route("/")
def list_vms():
    """List the managed VMs."""
    return v.list_vms()


@app.route("/status/<guest>")
def status_vm(guest):
    """Return the status of ``guest``."""
    return v.status(guest)


@app.route("/stop/<guest>")
def stop_vm(guest):
    """Stop ``guest``. Cross-site requests are refused by the hook."""
    out = execfunc(v.stop, guest)
    return out


@app.route("/start/<guest>")
def start_vm(guest):
    """Start ``guest``. Cross-site requests are refused by the hook."""
    out = execfunc(v.start, guest)
    return out


def main():
    # Loopback on purpose. In production this module is imported by the
    # wsgi.py of the vmmgrapi Ansible role and served by gunicorn on a
    # unix socket, behind an nginx that carries the TLS, the basic auth
    # and the ACL. This entry point is for local debugging only, and
    # listening on every interface would publish every route, in clear
    # text and unauthenticated, around all of that.
    app.run(host="127.0.0.1")


if __name__ == "__main__":
    main()
