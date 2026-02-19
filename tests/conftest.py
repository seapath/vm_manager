# Copyright (C) 2025, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

import os
import secrets

import pytest

from vm_manager.helpers.libvirt import LibVirtManager


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
