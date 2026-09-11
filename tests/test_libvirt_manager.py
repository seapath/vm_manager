# Copyright (C) 2025, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

import subprocess

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


class TestExportConfiguration:
    """export_configuration must not go through a shell.

    These tests stub subprocess.run, so they need no libvirt daemon.
    """

    def _stub(self, monkeypatch, stdout=b"<domain/>"):
        calls = []

        def fake_run(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, stdout=stdout)

        monkeypatch.setattr(
            "vm_manager.helpers.libvirt.subprocess.run", fake_run
        )
        return calls

    def test_runs_virsh_with_an_argv_list(self, tmp_path, monkeypatch):
        calls = self._stub(
            monkeypatch, stdout=b"<domain><name>test0</name></domain>"
        )
        xml_path = tmp_path / "test0.xml"

        LibVirtManager.export_configuration("test0", str(xml_path))

        command, kwargs = calls[0]
        assert command == [
            "/usr/bin/virsh",
            "-c",
            "qemu:///system",
            "dumpxml",
            "test0",
        ]
        assert kwargs["check"] is True
        assert kwargs["stdout"] == subprocess.PIPE
        assert not kwargs.get("shell", False)
        assert xml_path.read_bytes() == (
            b"<domain><name>test0</name></domain>"
        )

    def test_shell_metacharacters_are_a_single_argument(
        self, tmp_path, monkeypatch
    ):
        calls = self._stub(monkeypatch)
        payload = "test0; id; #"

        LibVirtManager.export_configuration(
            payload, str(tmp_path / "test0.xml")
        )

        command, kwargs = calls[0]
        assert command[-1] == payload
        assert command == [
            "/usr/bin/virsh",
            "-c",
            "qemu:///system",
            "dumpxml",
            payload,
        ]
        assert not kwargs.get("shell", False)

    def test_virsh_failure_propagates(self, tmp_path, monkeypatch):
        def fake_run(command, **kwargs):
            raise subprocess.CalledProcessError(1, command)

        monkeypatch.setattr(
            "vm_manager.helpers.libvirt.subprocess.run", fake_run
        )
        xml_path = tmp_path / "test0.xml"

        with pytest.raises(subprocess.CalledProcessError):
            LibVirtManager.export_configuration("test0", str(xml_path))

        assert not xml_path.exists()
