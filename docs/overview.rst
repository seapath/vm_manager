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
- ``vm_manager_api`` — Flask REST API (``/``, ``/status/<guest>``,
  ``/stop/<guest>``, ``/start/<guest>``)

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
