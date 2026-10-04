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

The state-changing routes are POST-only on purpose: a browser can issue
a cross-site GET without any preflight, so a GET-triggered ``/stop`` or
``/start`` would be a CSRF hole as soon as the API is reachable. POST
alone does not close that hole, since a cross-site form can still POST
blind; the authenticated nginx is what actually gates these calls.
Read-only routes stay on GET.
"""

from flask import Flask
import vm_manager as v

app = Flask(__name__)


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
    """List the managed VMs. Read-only, so it stays on GET."""
    return v.list_vms()


@app.route("/status/<guest>")
def status_vm(guest):
    """Return the status of ``guest``. Read-only, so it stays on GET."""
    return v.status(guest)


@app.route("/stop/<guest>", methods=["POST"])
def stop_vm(guest):
    """Stop ``guest``.

    POST-only: stopping a VM changes state, and a GET would let any
    cross-site request trigger it once the API is reachable.
    """
    out = execfunc(v.stop, guest)
    return out


@app.route("/start/<guest>", methods=["POST"])
def start_vm(guest):
    """Start ``guest``. POST-only, for the same reason as :func:`stop_vm`."""
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
