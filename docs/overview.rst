Overview
========

**vm_manager** is a Python tool for managing Virtual Machines on the
`SEAPATH <https://github.com/seapath>`_ platform.

Operating modes
---------------

The mode is auto-detected at import time based on available dependencies:

- **Standalone mode** (``vm_manager_libvirt.py``): manages VMs via KVM/libvirt
  only. Used when Pacemaker and Ceph RBD dependencies are not present.

- **Cluster mode** (``vm_manager_cluster.py``): manages VMs on a Pacemaker
  HA cluster with Ceph RBD storage. Activated when both ``rados``/``rbd``
  and ``crm`` (Pacemaker) are available.

Entry points
------------

- ``vm_manager_cmd`` — main CLI exposing all VM operations as subcommands
- ``libvirt_cmd`` — lower-level CLI for direct libvirt operations
- ``vm_manager_api`` — Flask REST API (``GET /``, ``GET /status/<guest>``,
  ``GET /stop/<guest>``, ``GET /start/<guest>``). Cross-site requests
  to the state-changing routes are refused when the browser identifies
  them (see below), and the API must stay behind the
  authenticated, TLS-terminating nginx.

REST API security
-----------------

The REST API authenticates nobody: it relies on the nginx in front of it
(TLS, basic auth, ACL) and must never be published directly.

The state-changing routes (``/stop`` and ``/start``) stay on ``GET`` to
keep the API compatible. To protect them against CSRF, the application
itself refuses requests that a browser marks as cross-site (``403``),
based on the ``Sec-Fetch-Site`` and ``Origin`` request headers. Requests
without these headers, such as ``curl`` or scripts, are accepted.

No web server configuration change is required: the protection lives in
``vm_manager_api`` and works with the existing nginx setup, as long as
nginx forwards the ``Origin`` and ``Sec-Fetch-Site`` headers unchanged
(the default) and the ``Host`` header as sent by the browser. nginx's
default is ``Host $proxy_host``, so this requires
``proxy_set_header Host $http_host;`` (set by the vmmgrapi role).
Otherwise same-origin requests carrying an ``Origin`` header are refused.

Limits: the check relies on headers sent by the browser. Browsers without
Fetch Metadata support (Safari < 16.4, Firefox < 90) send neither header
on a cross-site ``<img>`` GET, so such a request is not refused. Clients
sending neither header are always accepted.

Architecture
------------

Helper classes (used as context managers):

- :class:`~vm_manager.helpers.libvirt.LibVirtManager` — wraps
  ``libvirt-python`` for domain management
- :class:`~vm_manager.helpers.pacemaker.Pacemaker` — wraps the ``crm`` CLI
  via ``subprocess``
- :class:`~vm_manager.helpers.rbd_manager.RbdManager` — wraps Ceph
  ``rados``/``rbd`` Python bindings

Installation
------------

.. code-block:: bash

   pip install .

   # or with documentation dependencies
   pip install .[docs]

License
-------

Apache-2.0
