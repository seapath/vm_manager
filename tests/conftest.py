# Copyright (C) 2025, RTE (http://www.rte-france.com)
# Copyright (C) 2026 Savoir-faire Linux Inc.
# SPDX-License-Identifier: Apache-2.0

# vm_manager selects its backend when it is first imported, so the Ceph
# stubs have to be installed before any vm_manager import below. That is
# what forces the unusual import order here (see the E402 exemption for
# conftest.py in .flake8) and why this call sits at module level rather
# than in a fixture.
from ceph_stubs import install_ceph_stubs

install_ceph_stubs()

import os  # noqa: E402
import secrets  # noqa: E402

import pytest  # noqa: E402

from vm_manager.helpers.libvirt import LibVirtManager  # noqa: E402


@pytest.fixture
def vm_name():
    """Generate a unique VM name and ensure cleanup after test."""
    name = "testvm" + secrets.token_hex(4)
    yield name
    with LibVirtManager() as lvm:
        if name in lvm.list():
            try:
                lvm.force_stop(name)
            except Exception:
                pass
            try:
                lvm.undefine(name)
            except Exception:
                pass


@pytest.fixture
def libvirt_conn():
    """Provide a LibVirtManager connection for the test."""
    with LibVirtManager() as lvm:
        yield lvm


@pytest.fixture
def vm_xml_path():
    """Return the path to the test VM XML template."""
    return os.path.join(
        os.path.dirname(__file__),
        "..",
        "vm_manager",
        "testdata",
        "vm.xml",
    )
