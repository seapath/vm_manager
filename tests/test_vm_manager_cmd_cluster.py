# Copyright (C) 2026, Sprecher Automation
# SPDX-License-Identifier: Apache-2.0

"""
End-to-end test for the vm_manager_cmd CLI against a real cluster.

Requires Ceph + Pacemaker — the GitHub Actions CI workflow ignores
this file for that reason (see .github/workflows/ci.yml).

The test drives main() through the real backend without mocking
vm_manager.create(), which is the only way to prove that the string
'additional_disks' is consistent between vm_manager_cmd.py (dest=) and
vm_manager_cluster.py (vm_options.get).
"""

import os
import secrets
import subprocess
import xml.etree.ElementTree as ElementTree

import pytest

from vm_manager import vm_manager_cluster as vmc
from vm_manager.helpers.rbd_manager import RbdManager
from vm_manager.vm_manager_cluster import CEPH_CONF, NAMESPACE, POOL_NAME
from vm_manager.vm_manager_cmd import main


TESTDATA_XML_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "vm_manager",
    "testdata",
    "vm.xml",
)


def _read_test_xml_no_uuid():
    """Read the test VM template and strip the UUID to avoid collisions
    with VMs already present on the cluster from other tests.
    """
    with open(TESTDATA_XML_PATH) as f:
        xml = f.read()
    root = ElementTree.fromstring(xml)
    uuid_el = root.find("uuid")
    if uuid_el is not None:
        root.remove(uuid_el)
    return ElementTree.tostring(root, encoding="unicode")


@pytest.fixture
def cli_vm_name():
    """Unique VM name with teardown via vmc.remove."""
    name = "testvm" + secrets.token_hex(4)
    yield name
    try:
        vmc.remove(name)
    except Exception:
        pass


@pytest.fixture
def cli_qcow2_image(tmp_path):
    """Small temporary qcow2 image for the system disk."""
    path = tmp_path / "sys.qcow2"
    subprocess.run(
        ["qemu-img", "create", "-f", "qcow2", str(path), "64M"],
        check=True,
        capture_output=True,
    )
    return str(path)


@pytest.fixture
def cli_additional_qcow2_images(tmp_path):
    """Two small temporary qcow2 images for additional disks."""
    paths = []
    for i in range(2):
        path = tmp_path / f"data{i}.qcow2"
        subprocess.run(
            ["qemu-img", "create", "-f", "qcow2", str(path), "64M"],
            check=True,
            capture_output=True,
        )
        paths.append(str(path))
    return paths


class TestCreateAdditionalDiskEndToEnd:
    def test_cli_create_with_additional_disks(
        self,
        monkeypatch,
        tmp_path,
        cli_vm_name,
        cli_qcow2_image,
        cli_additional_qcow2_images,
    ):
        xml_file = tmp_path / "vm.xml"
        xml_file.write_text(_read_test_xml_no_uuid())

        argv = [
            "vm_manager_cmd",
            "create",
            "--name",
            cli_vm_name,
            "--xml",
            str(xml_file),
            "-i",
            cli_qcow2_image,
            "--additional-disk",
            cli_additional_qcow2_images[0],
            "--additional-disk",
            cli_additional_qcow2_images[1],
        ]
        monkeypatch.setattr("sys.argv", argv)

        main()

        assert cli_vm_name in vmc.list_vms()

        with RbdManager(CEPH_CONF, POOL_NAME, NAMESPACE) as rbd:
            group_images = rbd.list_group_images(cli_vm_name)

        assert f"system_{cli_vm_name}" in group_images
        assert f"data_{cli_vm_name}_0" in group_images
        assert f"data_{cli_vm_name}_1" in group_images
