# Copyright (C) 2025, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

import xml.etree.ElementTree as ElementTree

import libvirt
import pytest

from vm_manager import vm_manager_libvirt as vml
from vm_manager.exceptions import UuidConflictError


class TestListVms:
    def test_returns_list(self):
        result = vml.list_vms()
        assert isinstance(result, list)


class TestCreateXml:
    def test_name_replaced(self, vm_xml_path):
        with open(vm_xml_path) as f:
            xml = f.read()
        result = vml._create_xml(xml, "myvm")
        assert "<name>myvm</name>" in result

    def test_predefined_uuid_preserved(self, vm_xml_path):
        with open(vm_xml_path) as f:
            xml = f.read()
        result = vml._create_xml(xml, "myvm")
        root = ElementTree.fromstring(result)
        assert root.findtext("uuid") == "7b48b1fe-066a-41a6-aef4-f0a9c028f719"

    def test_empty_uuid_generates_new(self, vm_xml_path):
        with open(vm_xml_path) as f:
            xml = f.read()
        xml = xml.replace("7b48b1fe-066a-41a6-aef4-f0a9c028f719", "")
        result = vml._create_xml(xml, "myvm")
        root = ElementTree.fromstring(result)
        vm_uuid = root.findtext("uuid")
        assert vm_uuid
        assert vm_uuid != ""
        assert vm_uuid != "7b48b1fe-066a-41a6-aef4-f0a9c028f719"

    def test_missing_uuid_generates_new(self, vm_xml_path):
        with open(vm_xml_path) as f:
            xml = f.read()
        # Remove the entire <uuid> element
        root = ElementTree.fromstring(xml)
        uuid_el = root.find("uuid")
        if uuid_el is not None:
            root.remove(uuid_el)
        xml_no_uuid = ElementTree.tostring(root).decode()
        result = vml._create_xml(xml_no_uuid, "myvm")
        root = ElementTree.fromstring(result)
        vm_uuid = root.findtext("uuid")
        assert vm_uuid
        assert vm_uuid != ""
        assert vm_uuid != "7b48b1fe-066a-41a6-aef4-f0a9c028f719"


class TestCreate:
    def test_create_vm(self, vm_name, vm_xml_path):
        with open(vm_xml_path) as f:
            xml = f.read()
        args = {
            "base_xml": xml,
            "name": vm_name,
            "autostart": False,
        }
        vml.create(args)
        assert vm_name in vml.list_vms()

    def test_create_with_autostart(self, vm_name, vm_xml_path):
        with open(vm_xml_path) as f:
            xml = f.read()
        args = {
            "base_xml": xml,
            "name": vm_name,
            "autostart": True,
        }
        vml.create(args)
        assert vm_name in vml.list_vms()
        conn = libvirt.open("qemu:///system")
        domain = conn.lookupByName(vm_name)
        assert domain.autostart() == 1
        conn.close()


class TestRemove:
    def test_remove_stopped_vm(self, vm_name, vm_xml_path):
        with open(vm_xml_path) as f:
            xml = f.read()
        vml.create({"base_xml": xml, "name": vm_name, "autostart": False})
        vml.remove(vm_name)
        assert vm_name not in vml.list_vms()

    def test_remove_running_vm(self, vm_name, vm_xml_path):
        with open(vm_xml_path) as f:
            xml = f.read()
        vml.create({"base_xml": xml, "name": vm_name, "autostart": False})
        vml.start(vm_name)
        vml.remove(vm_name)
        assert vm_name not in vml.list_vms()


class TestStartStop:
    def test_start(self, vm_name, vm_xml_path):
        with open(vm_xml_path) as f:
            xml = f.read()
        vml.create({"base_xml": xml, "name": vm_name, "autostart": False})
        vml.start(vm_name)
        assert vml.status(vm_name) == "Started"

    def test_force_stop(self, vm_name, vm_xml_path):
        with open(vm_xml_path) as f:
            xml = f.read()
        vml.create({"base_xml": xml, "name": vm_name, "autostart": False})
        vml.start(vm_name)
        vml.stop(vm_name, force=True)
        assert vml.status(vm_name) == "Stopped"


class TestStatus:
    def test_stopped_after_create(self, vm_name, vm_xml_path):
        with open(vm_xml_path) as f:
            xml = f.read()
        vml.create({"base_xml": xml, "name": vm_name, "autostart": False})
        assert vml.status(vm_name) == "Stopped"

    def test_started_after_start(self, vm_name, vm_xml_path):
        with open(vm_xml_path) as f:
            xml = f.read()
        vml.create({"base_xml": xml, "name": vm_name, "autostart": False})
        vml.start(vm_name)
        assert vml.status(vm_name) == "Started"


class TestListAllUuids:
    def test_returns_dict(self):
        result = vml.list_all_uuids()
        assert isinstance(result, dict)

    def test_created_vm_uuid_appears(self, vm_name, vm_xml_path):
        with open(vm_xml_path) as f:
            xml = f.read()
        vml.create({"base_xml": xml, "name": vm_name, "autostart": False})
        uuids = vml.list_all_uuids()
        assert vm_name in uuids.values()


class TestUuidCollision:
    def test_duplicate_uuid_raises(self, vm_name, vm_xml_path):
        with open(vm_xml_path) as f:
            xml = f.read()
        # Create first VM with the predefined UUID
        vml.create({"base_xml": xml, "name": vm_name, "autostart": False})
        # Attempt to create second VM with same UUID
        with pytest.raises(UuidConflictError):
            vml.create(
                {
                    "base_xml": xml,
                    "name": vm_name + "dup",
                    "autostart": False,
                }
            )
        # Clean up the second VM if it was somehow created
        if vm_name + "dup" in vml.list_vms():
            vml.remove(vm_name + "dup")


class TestAutostart:
    def test_enable_autostart(self, vm_name, vm_xml_path):
        with open(vm_xml_path) as f:
            xml = f.read()
        vml.create({"base_xml": xml, "name": vm_name, "autostart": False})
        vml.autostart(vm_name, True)
        conn = libvirt.open("qemu:///system")
        domain = conn.lookupByName(vm_name)
        assert domain.autostart() == 1
        conn.close()

    def test_disable_autostart(self, vm_name, vm_xml_path):
        with open(vm_xml_path) as f:
            xml = f.read()
        vml.create({"base_xml": xml, "name": vm_name, "autostart": True})
        vml.autostart(vm_name, False)
        conn = libvirt.open("qemu:///system")
        domain = conn.lookupByName(vm_name)
        assert domain.autostart() == 0
        conn.close()
