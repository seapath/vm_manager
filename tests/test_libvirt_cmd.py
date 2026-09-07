# Copyright (C) 2026, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""
Unit tests for the libvirt_cmd CLI, with no libvirt daemon.

main() reads sys.argv and talks to LibVirtManager, so the tests drive it
through argv and replace the manager with a recorder. Nothing here opens
a connection.
"""

import pytest

from vm_manager.helpers import libvirt_cmd

VM = "vm1"


class FakeManager:
    """Recording stand-in for LibVirtManager, usable as a context manager.

    The class records what every instance was asked to do, because main()
    builds its own instance and the test never sees it.
    """

    calls = []
    exported = []
    vms = [VM, "vm2"]
    secrets = {"client.libvirt secret": "uuid-a"}

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def list(self):
        type(self).calls.append("list")
        return list(self.vms)

    def get_virsh_secrets(self):
        type(self).calls.append("get_virsh_secrets")
        return dict(self.secrets)

    def define(self, xml):
        type(self).calls.append(("define", xml))

    @classmethod
    def export_configuration(cls, domain, destination):
        cls.exported.append((domain, destination))


@pytest.fixture
def manager(monkeypatch):
    """Replace LibVirtManager as libvirt_cmd sees it."""
    FakeManager.calls = []
    FakeManager.exported = []
    monkeypatch.setattr(libvirt_cmd, "LibVirtManager", FakeManager)
    return FakeManager


@pytest.fixture
def run_cli(monkeypatch, manager):
    """Run main() with the given command line."""

    def run(*argv):
        monkeypatch.setattr("sys.argv", ["libvirt_cmd"] + list(argv))
        libvirt_cmd.main()

    return run


class TestParser:
    """get_parser(): the argument parser sphinx-argparse also reads."""

    def test_a_command_is_required(self):
        with pytest.raises(SystemExit):
            libvirt_cmd.get_parser().parse_args([])

    @pytest.mark.parametrize(
        "command", ["list", "secrets", "export", "define"]
    )
    def test_every_command_is_declared(self, command):
        assert command in libvirt_cmd.get_parser().format_help()

    def test_export_takes_a_domain_and_a_destination(self):
        args = libvirt_cmd.get_parser().parse_args(
            ["export", VM, "/tmp/vm1.xml"]
        )
        assert (args.domain, args.destination) == (VM, "/tmp/vm1.xml")

    def test_export_needs_both_arguments(self):
        with pytest.raises(SystemExit):
            libvirt_cmd.get_parser().parse_args(["export", VM])

    def test_define_takes_an_xml_path(self):
        args = libvirt_cmd.get_parser().parse_args(["define", "/tmp/vm1.xml"])
        assert args.xml == "/tmp/vm1.xml"

    def test_an_unknown_command_is_refused(self):
        with pytest.raises(SystemExit):
            libvirt_cmd.get_parser().parse_args(["nonsense"])


class TestList:
    """libvirt_cmd list."""

    def test_the_vms_are_printed_one_per_line(self, run_cli, capsys):
        run_cli("list")
        assert capsys.readouterr().out == VM + "\nvm2\n"

    def test_the_manager_is_asked(self, run_cli, manager):
        run_cli("list")
        assert manager.calls == ["list"]

    def test_no_vm_prints_nothing(self, run_cli, manager, capsys):
        manager.vms = []
        try:
            run_cli("list")
            assert capsys.readouterr().out == ""
        finally:
            manager.vms = [VM, "vm2"]


class TestSecrets:
    """libvirt_cmd secrets."""

    def test_each_secret_is_printed_as_name_and_value(self, run_cli, capsys):
        run_cli("secrets")
        assert capsys.readouterr().out == "client.libvirt secret: uuid-a\n"

    def test_the_manager_is_asked(self, run_cli, manager):
        run_cli("secrets")
        assert manager.calls == ["get_virsh_secrets"]


class TestDefine:
    """libvirt_cmd define."""

    XML = "<domain type='kvm'><name>vm1</name></domain>"

    def test_the_file_content_is_handed_over(self, run_cli, manager, tmp_path):
        path = tmp_path / "vm1.xml"
        path.write_text(self.XML)
        run_cli("define", str(path))
        assert manager.calls == [("define", self.XML)]

    def test_a_missing_file_is_reported(self, run_cli, tmp_path):
        with pytest.raises(IOError):
            run_cli("define", str(tmp_path / "absent.xml"))


class TestExport:
    """libvirt_cmd export."""

    def test_the_domain_and_destination_are_passed_on(self, run_cli, manager):
        run_cli("export", VM, "/tmp/vm1.xml")
        assert manager.exported == [(VM, "/tmp/vm1.xml")]

    def test_no_connection_is_opened(self, run_cli, manager):
        run_cli("export", VM, "/tmp/vm1.xml")
        assert manager.calls == []
