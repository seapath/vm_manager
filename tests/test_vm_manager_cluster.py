# Copyright (C) 2025, RTE (http://www.rte-france.com)
# Copyright (C) 2026 Savoir-faire Linux Inc.
# SPDX-License-Identifier: Apache-2.0

import os
import secrets
import subprocess
import tempfile
import xml.etree.ElementTree as ElementTree

import pytest

from vm_manager import vm_manager_cluster as vmc
from vm_manager.helpers.libvirt import LibVirtManager

TESTDATA_XML_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "vm_manager",
    "testdata",
    "vm.xml",
)


def _read_test_xml():
    with open(TESTDATA_XML_PATH) as f:
        return f.read()


@pytest.fixture
def vm_name():
    """Generate a unique VM name and ensure cleanup after test."""
    name = "testvm" + secrets.token_hex(4)
    yield name
    # Cleanup: remove VM from all subsystems
    try:
        vmc.remove(name)
    except Exception:
        pass


@pytest.fixture
def second_vm_name():
    """Generate a second unique VM name for clone tests."""
    name = "testvm" + secrets.token_hex(4)
    yield name
    try:
        vmc.remove(name)
    except Exception:
        pass


@pytest.fixture
def qcow2_image():
    """Create a small temporary qcow2 image for testing."""
    with tempfile.NamedTemporaryFile(suffix=".qcow2", delete=False) as f:
        path = f.name
    subprocess.run(
        ["qemu-img", "create", "-f", "qcow2", path, "64M"],
        check=True,
        capture_output=True,
    )
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def created_vm(vm_name, qcow2_image):
    """Create a VM and return its name. Enables by default."""
    xml = _read_test_xml()
    vmc.create(
        {
            "name": vm_name,
            "image": qcow2_image,
            "base_xml": xml,
        }
    )
    return vm_name


@pytest.fixture
def disabled_vm(vm_name, qcow2_image):
    """Create a disabled VM and return its name."""
    xml = _read_test_xml()
    vmc.create(
        {
            "name": vm_name,
            "image": qcow2_image,
            "base_xml": xml,
            "enable": False,
        }
    )
    return vm_name


# ── _check_name ──────────────────────────────────────────────────────


class TestCheckName:
    def test_valid_alphanumeric(self):
        vmc._check_name("myvm1")

    def test_reserved_name_raises(self):
        with pytest.raises(ValueError, match="reserved word"):
            vmc._check_name("xml")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            vmc._check_name("")

    def test_special_chars_raises(self):
        with pytest.raises(ValueError):
            vmc._check_name("my-vm")

    def test_spaces_raises(self):
        with pytest.raises(ValueError):
            vmc._check_name("my vm")

    def test_underscore_raises(self):
        with pytest.raises(ValueError):
            vmc._check_name("my_vm")

    def test_non_string_raises(self):
        with pytest.raises(ValueError):
            vmc._check_name(123)

    def test_none_raises(self):
        with pytest.raises(ValueError):
            vmc._check_name(None)


# ── list_vms ─────────────────────────────────────────────────────────


class TestListVms:
    def test_returns_list(self):
        result = vmc.list_vms()
        assert isinstance(result, list)

    def test_returns_list_enabled(self):
        result = vmc.list_vms(enabled=True)
        assert isinstance(result, list)

    def test_created_vm_in_list(self, created_vm):
        assert created_vm in vmc.list_vms()

    def test_created_vm_in_enabled_list(self, created_vm):
        assert created_vm in vmc.list_vms(enabled=True)

    def test_disabled_vm_in_all_list(self, disabled_vm):
        assert disabled_vm in vmc.list_vms()

    def test_disabled_vm_not_in_enabled_list(self, disabled_vm):
        assert disabled_vm not in vmc.list_vms(enabled=True)


# ── create ───────────────────────────────────────────────────────────


class TestCreate:
    def test_create_vm(self, created_vm):
        assert created_vm in vmc.list_vms()

    def test_create_invalid_name_raises(self, qcow2_image):
        with pytest.raises(ValueError):
            vmc.create(
                {
                    "name": "test-vm",
                    "image": qcow2_image,
                    "base_xml": _read_test_xml(),
                }
            )

    def test_create_missing_image_raises(self):
        with pytest.raises(IOError):
            vmc.create(
                {
                    "name": "testvm",
                    "image": "/nonexistent/disk.qcow2",
                    "base_xml": _read_test_xml(),
                }
            )

    def test_create_invalid_metadata_type_raises(self, qcow2_image):
        with pytest.raises(ValueError, match="metadata"):
            vmc.create(
                {
                    "name": "testvm",
                    "image": qcow2_image,
                    "base_xml": _read_test_xml(),
                    "metadata": "not_a_dict",
                }
            )

    def test_create_disabled(self, disabled_vm):
        assert vmc.status(disabled_vm) == "Disabled"

    def test_create_already_exists_raises(self, created_vm, qcow2_image):
        with pytest.raises(Exception, match="already exists"):
            vmc.create(
                {
                    "name": created_vm,
                    "image": qcow2_image,
                    "base_xml": _read_test_xml(),
                }
            )

    def test_create_with_force(self, created_vm, qcow2_image):
        vmc.create(
            {
                "name": created_vm,
                "image": qcow2_image,
                "base_xml": _read_test_xml(),
                "force": True,
            }
        )
        assert created_vm in vmc.list_vms()

    def test_create_with_metadata(self, vm_name, qcow2_image):
        vmc.create(
            {
                "name": vm_name,
                "image": qcow2_image,
                "base_xml": _read_test_xml(),
                "metadata": {"mykey": "myvalue"},
            }
        )
        assert vmc.get_metadata(vm_name, "mykey") == "myvalue"

    def test_create_nones_filtered(self, vm_name, qcow2_image):
        vmc.create(
            {
                "name": vm_name,
                "image": qcow2_image,
                "base_xml": _read_test_xml(),
                "pinned_host": None,
                "preferred_host": None,
            }
        )
        assert vm_name in vmc.list_vms()


# ── _create_xml ──────────────────────────────────────────────────────


class TestCreateXml:
    def test_name_replaced(self):
        xml = _read_test_xml()
        result = vmc._create_xml(xml, "myvm")
        assert "<name>myvm</name>" in result

    def test_uuid_preserved_when_provided(self):
        xml = _read_test_xml()
        result = vmc._create_xml(xml, "myvm")
        assert "7b48b1fe-066a-41a6-aef4-f0a9c028f719" in result

    def test_uuid_generated_when_not_provided(self):
        xml = _read_test_xml()
        xml = xml.replace(
            "<uuid>7b48b1fe-066a-41a6-aef4-f0a9c028f719</uuid>", ""
        )
        result = vmc._create_xml(xml, "myvm")
        assert "<uuid>" in result
        assert "7b48b1fe-066a-41a6-aef4-f0a9c028f719" not in result

    def test_rbd_disk_added(self):
        xml = _read_test_xml()
        result = vmc._create_xml(xml, "myvm")
        assert "rbd/system_myvm" in result
        assert 'type="network"' in result

    def test_custom_disk_bus(self):
        xml = _read_test_xml()
        result = vmc._create_xml(xml, "myvm", target_disk_bus="scsi")
        assert 'bus="scsi"' in result


# ── status ───────────────────────────────────────────────────────────


class TestStatus:
    def test_undefined_vm(self):
        assert vmc.status("nonexistentvmxyz") == "Undefined"

    def test_disabled_vm(self, disabled_vm):
        assert vmc.status(disabled_vm) == "Disabled"

    def test_started_vm(self, created_vm):
        assert vmc.status(created_vm) == "Started"


# ── is_enabled ───────────────────────────────────────────────────────


class TestIsEnabled:
    def test_enabled(self, created_vm):
        assert vmc.is_enabled(created_vm) is True

    def test_disabled(self, disabled_vm):
        assert vmc.is_enabled(disabled_vm) is False

    def test_nonexistent(self):
        assert vmc.is_enabled("nonexistentvmxyz") is False


# ── start / stop ─────────────────────────────────────────────────────


class TestStartStop:
    def test_stop_running_vm(self, created_vm):
        vmc.stop(created_vm)
        assert vmc.status(created_vm) == "Stopped (disabled)"

    def test_start_stopped_vm(self, created_vm):
        vmc.stop(created_vm)
        vmc.start(created_vm)
        assert vmc.status(created_vm) == "Started"

    def test_start_already_started(self, created_vm):
        # Should not raise
        vmc.start(created_vm)
        assert vmc.status(created_vm) == "Started"

    def test_stop_already_stopped(self, created_vm):
        vmc.stop(created_vm)
        # Should not raise
        vmc.stop(created_vm)
        assert vmc.status(created_vm) == "Stopped (disabled)"

    def test_start_not_enabled_raises(self, disabled_vm):
        with pytest.raises(Exception, match="not on the cluster"):
            vmc.start(disabled_vm)

    def test_stop_not_enabled_raises(self, disabled_vm):
        with pytest.raises(Exception, match="not on the cluster"):
            vmc.stop(disabled_vm)


# ── enable_vm / disable_vm ───────────────────────────────────────────


class TestEnableDisable:
    def test_enable_disabled_vm(self, disabled_vm):
        vmc.enable_vm(disabled_vm)
        assert vmc.is_enabled(disabled_vm) is True
        assert vmc.status(disabled_vm) == "Started"

    def test_enable_with_nostart(self, disabled_vm):
        vmc.enable_vm(disabled_vm, nostart=True)
        assert vmc.is_enabled(disabled_vm) is True
        assert vmc.status(disabled_vm) == "Stopped (disabled)"

    def test_disable_running_vm(self, created_vm):
        vmc.disable_vm(created_vm)
        assert vmc.is_enabled(created_vm) is False
        assert vmc.status(created_vm) == "Disabled"

    def test_disable_already_disabled(self, disabled_vm):
        # Should not raise
        vmc.disable_vm(disabled_vm)

    def test_enable_already_enabled(self, created_vm):
        # Should not raise
        vmc.enable_vm(created_vm)
        assert vmc.status(created_vm) == "Started"


# ── remove ───────────────────────────────────────────────────────────


class TestRemove:
    def test_remove_enabled_vm(self, vm_name, qcow2_image):
        vmc.create(
            {
                "name": vm_name,
                "image": qcow2_image,
                "base_xml": _read_test_xml(),
            }
        )
        vmc.remove(vm_name)
        assert vmc.status(vm_name) == "Undefined"

    def test_remove_disabled_vm(self, vm_name, qcow2_image):
        vmc.create(
            {
                "name": vm_name,
                "image": qcow2_image,
                "base_xml": _read_test_xml(),
                "enable": False,
            }
        )
        vmc.remove(vm_name)
        assert vmc.status(vm_name) == "Undefined"


# ── Snapshots ────────────────────────────────────────────────────────


class TestSnapshots:
    def test_create_snapshot(self, created_vm):
        vmc.create_snapshot(created_vm, "snap1")
        assert "snap1" in vmc.list_snapshots(created_vm)

    def test_remove_snapshot(self, created_vm):
        vmc.create_snapshot(created_vm, "snap1")
        vmc.remove_snapshot(created_vm, "snap1")
        assert "snap1" not in vmc.list_snapshots(created_vm)

    def test_list_snapshots_empty(self, created_vm):
        result = vmc.list_snapshots(created_vm)
        assert isinstance(result, list)

    def test_create_duplicate_snapshot_raises(self, created_vm):
        vmc.create_snapshot(created_vm, "snap1")
        with pytest.raises(Exception, match="already exists"):
            vmc.create_snapshot(created_vm, "snap1")

    def test_invalid_snapshot_name_raises(self, created_vm):
        with pytest.raises(ValueError):
            vmc.create_snapshot(created_vm, "snap-1")

    def test_rollback_snapshot(self, created_vm):
        vmc.create_snapshot(created_vm, "snap1")
        vmc.rollback_snapshot(created_vm, "snap1")

    def test_rollback_nonexistent_raises(self, created_vm):
        with pytest.raises(Exception, match="does not exist"):
            vmc.rollback_snapshot(created_vm, "nosuchsnap")

    def test_purge_all_snapshots(self, created_vm):
        vmc.create_snapshot(created_vm, "snap1")
        vmc.create_snapshot(created_vm, "snap2")
        vmc.purge_image(created_vm)
        assert len(vmc.list_snapshots(created_vm)) == 0

    def test_purge_by_number(self, created_vm):
        vmc.create_snapshot(created_vm, "snap1")
        vmc.create_snapshot(created_vm, "snap2")
        vmc.create_snapshot(created_vm, "snap3")
        vmc.purge_image(created_vm, number=2)
        snaps = vmc.list_snapshots(created_vm)
        assert len(snaps) == 1

    def test_purge_invalid_args(self):
        with pytest.raises(ValueError, match="not datetime"):
            vmc.purge_image("vm", date="2025-01-01")

        with pytest.raises(ValueError, match="positive integer"):
            vmc.purge_image("vm", number=-1)


# ── Metadata ─────────────────────────────────────────────────────────


class TestMetadata:
    def test_set_and_get_metadata(self, created_vm):
        vmc.set_metadata(created_vm, "mykey", "myvalue")
        assert vmc.get_metadata(created_vm, "mykey") == "myvalue"

    def test_list_metadata(self, created_vm):
        vmc.set_metadata(created_vm, "key1", "val1")
        metadata = vmc.list_metadata(created_vm)
        assert isinstance(metadata, list)
        assert "key1" in metadata

    def test_set_metadata_invalid_name_raises(self, created_vm):
        with pytest.raises(ValueError):
            vmc.set_metadata(created_vm, "bad-key", "value1")


# ── clone ────────────────────────────────────────────────────────────


class TestClone:
    def test_clone_vm(self, created_vm, second_vm_name):
        vmc.clone(
            {
                "name": created_vm,
                "dst_name": second_vm_name,
            }
        )
        assert second_vm_name in vmc.list_vms()

    def test_clone_same_name_raises(self):
        with pytest.raises(ValueError, match="same name"):
            vmc.clone({"name": "myvm", "dst_name": "myvm"})

    def test_clone_invalid_dst_name_raises(self):
        with pytest.raises(ValueError):
            vmc.clone({"name": "myvm", "dst_name": "bad-name"})

    def test_clone_invalid_metadata_type_raises(self):
        with pytest.raises(ValueError, match="metadata"):
            vmc.clone(
                {
                    "name": "srcvm",
                    "dst_name": "dstvm",
                    "metadata": "not_a_dict",
                }
            )


# ── add_to_cluster ───────────────────────────────────────────────────


@pytest.fixture
def libvirt_vm(vm_name, qcow2_image):
    """Define a VM in libvirt with a disk, for import tests."""
    xml_template = _read_test_xml()
    root = ElementTree.fromstring(xml_template)
    root.find("name").text = vm_name
    # Add a disk device pointing to the qcow2 image
    devices = root.find("devices")
    disk = ElementTree.SubElement(devices, "disk", type="file", device="disk")
    ElementTree.SubElement(disk, "driver", name="qemu", type="qcow2")
    ElementTree.SubElement(disk, "source", file=qcow2_image)
    ElementTree.SubElement(disk, "target", dev="vda", bus="virtio")
    vm_xml = ElementTree.tostring(root, encoding="unicode")
    with LibVirtManager() as lvm:
        lvm.define(vm_xml)
    yield vm_name
    # Cleanup: undefine from libvirt if still present
    try:
        with LibVirtManager() as lvm:
            if vm_name in lvm.list():
                lvm.undefine(vm_name)
    except Exception:
        pass


class TestAddToCluster:
    def test_add_to_cluster(self, libvirt_vm, qcow2_image):
        """Add a libvirt VM to the cluster."""
        vmc.add_to_cluster(
            {
                "name": libvirt_vm,
                "image": qcow2_image,
            }
        )
        assert libvirt_vm in vmc.list_vms()

    def test_add_to_cluster_auto_disk(self, libvirt_vm):
        """Add a libvirt VM without specifying image path."""
        vmc.add_to_cluster({"name": libvirt_vm})
        assert libvirt_vm in vmc.list_vms()

    def test_add_to_cluster_with_new_name(
        self, libvirt_vm, second_vm_name, qcow2_image
    ):
        """Add a libvirt VM with a different target name."""
        vmc.add_to_cluster(
            {
                "name": libvirt_vm,
                "new_name": second_vm_name,
                "image": qcow2_image,
            }
        )
        assert second_vm_name in vmc.list_vms()

    def test_add_to_cluster_disabled(self, libvirt_vm, qcow2_image):
        """Add a libvirt VM as disabled."""
        vmc.add_to_cluster(
            {
                "name": libvirt_vm,
                "image": qcow2_image,
                "enable": False,
            }
        )
        assert vmc.status(libvirt_vm) == "Disabled"

    def test_add_nonexistent_vm_raises(self):
        """Add a VM that doesn't exist in libvirt."""
        with pytest.raises(Exception, match="does not exist"):
            vmc.add_to_cluster(
                {
                    "name": "nonexistentvmxyz",
                    "image": "/tmp/fake.qcow2",
                }
            )

    def test_add_invalid_name_raises(self, libvirt_vm, qcow2_image):
        """Add with an invalid target name."""
        with pytest.raises(ValueError):
            vmc.add_to_cluster(
                {
                    "name": libvirt_vm,
                    "new_name": "bad-name",
                    "image": qcow2_image,
                }
            )

    def test_add_multi_disk_vm_raises(self, vm_name, qcow2_image):
        """Add a VM with multiple disks raises an exception."""
        xml_template = _read_test_xml()
        root = ElementTree.fromstring(xml_template)
        root.find("name").text = vm_name
        devices = root.find("devices")
        for dev_name in ("vda", "vdb"):
            disk = ElementTree.SubElement(
                devices, "disk", type="file", device="disk"
            )
            ElementTree.SubElement(disk, "driver", name="qemu", type="qcow2")
            ElementTree.SubElement(disk, "source", file=qcow2_image)
            ElementTree.SubElement(disk, "target", dev=dev_name, bus="virtio")
        vm_xml = ElementTree.tostring(root, encoding="unicode")
        with LibVirtManager() as lvm:
            lvm.define(vm_xml)
        try:
            with pytest.raises(Exception, match="more than one disk"):
                vmc.add_to_cluster(
                    {
                        "name": vm_name,
                        "image": qcow2_image,
                    }
                )
        finally:
            with LibVirtManager() as lvm:
                if vm_name in lvm.list():
                    lvm.undefine(vm_name)


# ── console ──────────────────────────────────────────────────────────


class TestConsole:
    def test_console_nonexistent_vm(self):
        with pytest.raises(SystemExit):
            vmc.console("nonexistentvmxyz")
