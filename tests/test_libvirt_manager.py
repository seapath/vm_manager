# Copyright (C) 2025, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

import libvirt
import pytest

from vm_manager.helpers.libvirt import LibVirtManager


class TestConnection:
    def test_context_manager(self):
        with LibVirtManager() as lvm:
            assert lvm._conn is not None
            assert lvm._conn.isAlive()

    def test_close(self):
        lvm = LibVirtManager()
        lvm.close()


class TestList:
    def test_list_returns_list(self, libvirt_conn):
        result = libvirt_conn.list()
        assert isinstance(result, list)

    def test_list_contains_defined_vm(
        self, libvirt_conn, vm_name, vm_xml_path
    ):
        with open(vm_xml_path) as f:
            xml = f.read()
        xml = xml.replace("test0", vm_name)
        libvirt_conn.define(xml)
        assert vm_name in libvirt_conn.list()


class TestDefine:
    def test_define_valid_xml(self, libvirt_conn, vm_name, vm_xml_path):
        with open(vm_xml_path) as f:
            xml = f.read()
        xml = xml.replace("test0", vm_name)
        libvirt_conn.define(xml)
        assert vm_name in libvirt_conn.list()

    def test_define_invalid_xml_raises(self, libvirt_conn):
        with pytest.raises(libvirt.libvirtError):
            libvirt_conn.define("<invalid/>")


class TestUndefine:
    def test_undefine_removes_domain(self, libvirt_conn, vm_name, vm_xml_path):
        with open(vm_xml_path) as f:
            xml = f.read()
        xml = xml.replace("test0", vm_name)
        libvirt_conn.define(xml)
        libvirt_conn.undefine(vm_name)
        assert vm_name not in libvirt_conn.list()

    def test_undefine_nonexistent_raises(self, libvirt_conn):
        with pytest.raises(libvirt.libvirtError):
            libvirt_conn.undefine("nonexistent_vm_xyz")


class TestStartStop:
    def test_start_and_force_stop(self, libvirt_conn, vm_name, vm_xml_path):
        with open(vm_xml_path) as f:
            xml = f.read()
        xml = xml.replace("test0", vm_name)
        libvirt_conn.define(xml)
        libvirt_conn.start(vm_name)
        assert libvirt_conn.status(vm_name) == "Started"
        libvirt_conn.force_stop(vm_name)
        assert libvirt_conn.status(vm_name) == "Stopped"


class TestStatus:
    def test_status_stopped(self, libvirt_conn, vm_name, vm_xml_path):
        with open(vm_xml_path) as f:
            xml = f.read()
        xml = xml.replace("test0", vm_name)
        libvirt_conn.define(xml)
        assert libvirt_conn.status(vm_name) == "Stopped"

    def test_status_started(self, libvirt_conn, vm_name, vm_xml_path):
        with open(vm_xml_path) as f:
            xml = f.read()
        xml = xml.replace("test0", vm_name)
        libvirt_conn.define(xml)
        libvirt_conn.start(vm_name)
        assert libvirt_conn.status(vm_name) == "Started"

    def test_status_undefined(self, libvirt_conn):
        assert libvirt_conn.status("nonexistent_vm_xyz") == "Undefined"


class TestAutostart:
    def test_enable_autostart(self, libvirt_conn, vm_name, vm_xml_path):
        with open(vm_xml_path) as f:
            xml = f.read()
        xml = xml.replace("test0", vm_name)
        libvirt_conn.define(xml)
        libvirt_conn.set_autostart(vm_name, True)
        domain = libvirt_conn._conn.lookupByName(vm_name)
        assert domain.autostart() == 1

    def test_disable_autostart(self, libvirt_conn, vm_name, vm_xml_path):
        with open(vm_xml_path) as f:
            xml = f.read()
        xml = xml.replace("test0", vm_name)
        libvirt_conn.define(xml)
        libvirt_conn.set_autostart(vm_name, True)
        libvirt_conn.set_autostart(vm_name, False)
        domain = libvirt_conn._conn.lookupByName(vm_name)
        assert domain.autostart() == 0
