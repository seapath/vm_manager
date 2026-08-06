#!/usr/bin/env python3
# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

from flask import Flask
from flask_wtf.csrf import CSRFProtect
import vm_manager as v

app = Flask(__name__)
csrf = CSRFProtect()
csrf.init_app(app)


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
    return v.list_vms()


@app.route("/status/<guest>")
def status_vm(guest):
    return v.status(guest)


@app.route("/stop/<guest>")
def stop_vm(guest):
    out = execfunc(v.stop, guest)
    return out


@app.route("/start/<guest>")
def start_vm(guest):
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
