# Copyright (C) 2026 Savoir-faire Linux Inc.
# SPDX-License-Identifier: Apache-2.0

"""
Import-time stubs for the Ceph Python bindings.

vm_manager picks its backend when it is first imported (see
vm_manager/__init__.py): if ``rados`` and ``rbd`` are importable it exposes
the cluster API, otherwise it falls back to the libvirt-only API. Those
bindings ship with Ceph itself and are not installable from PyPI, so on a
plain CI runner ``cluster_mode`` is False and every cluster-side test is
skipped, including the ones that only exercise argparse or pure helper
functions and need no cluster at all.

Installing these stubs before vm_manager is imported makes ``cluster_mode``
True so those tests run. The stubs only satisfy the import: instantiating
one raises, so a test that reaches real Ceph code fails loudly instead of
quietly passing against a fake.

On a machine with Ceph installed the genuine bindings are found and nothing
is stubbed.
"""

import sys
import types


class _CephStub:
    """Placeholder for a Ceph binding class, unusable on purpose."""

    def __init__(self, *args, **kwargs):
        raise RuntimeError(
            "{} is a test stub: this test reached real Ceph code, which "
            "needs a live cluster. Mock the RbdManager method under test, "
            "or move the test to tests/test_vm_manager_cluster.py.".format(
                type(self).__name__
            )
        )


class Rados(_CephStub):
    """Stub for :class:`rados.Rados`."""


class RBD(_CephStub):
    """Stub for :class:`rbd.RBD`."""


class Group(_CephStub):
    """Stub for :class:`rbd.Group`."""


class Image(_CephStub):
    """Stub for :class:`rbd.Image`."""


def _make_module(name, attrs):
    """Build a stub module exposing ``attrs``.

    :param name: the module name to register in :data:`sys.modules`
    :param attrs: a dict of attribute name to value
    :return: the newly created module
    """
    module = types.ModuleType(name)
    module.__doc__ = "Test stub for the Ceph '{}' bindings.".format(name)
    for attr_name, value in attrs.items():
        setattr(module, attr_name, value)
    return module


def install_ceph_stubs():
    """Register stub ``rados`` and ``rbd`` modules if the real ones are absent.

    Must be called before vm_manager is imported for the first time.

    :return: True if stubs were installed, False if the real Ceph bindings
        are available and were left alone
    """
    try:
        import rados  # noqa: F401
        import rbd  # noqa: F401
    except ModuleNotFoundError:
        pass
    else:
        return False

    sys.modules["rados"] = _make_module("rados", {"Rados": Rados})
    sys.modules["rbd"] = _make_module(
        "rbd", {"RBD": RBD, "Group": Group, "Image": Image}
    )
    return True
