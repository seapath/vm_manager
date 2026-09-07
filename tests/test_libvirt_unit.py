# Copyright (C) 2026, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""
Unit tests for the libvirt helper, with no libvirt daemon.

test_libvirt_manager.py drives a real qemu:///system and covers what a
running daemon can be made to do. The rest needs a domain in a state a
daemon will not produce on demand, a crashed or PM-suspended one for
instance, so those paths are exercised here against a fake connection.

Only libvirt.open() is replaced. Every constant and exception type still
comes from the real module, so a test asserting on
VIR_DOMAIN_PMSUSPENDED asserts on the value the daemon would report.
"""

import subprocess

import libvirt
import pytest

from vm_manager.helpers import libvirt as libvirt_helper
from vm_manager.helpers.libvirt import LibVirtManager

VM = "vm1"


class FakeDomain:
    """The subset of a libvirt domain the helper uses."""

    def __init__(self, name=VM, uuid="uuid-1", state=None):
        self._name = name
        self._uuid = uuid
        self._state = libvirt.VIR_DOMAIN_SHUTOFF if state is None else state
        self.calls = []
        self.autostart = None

    def name(self):
        return self._name

    def UUIDString(self):
        return self._uuid

    def state(self):
        return (self._state, 0)

    def create(self):
        self.calls.append("create")

    def shutdown(self):
        self.calls.append("shutdown")

    def destroy(self):
        self.calls.append("destroy")

    def undefineFlags(self, flags):
        self.calls.append(("undefineFlags", flags))

    def setAutostart(self, value):
        self.autostart = value


class FakeSecret:
    """The subset of a libvirt secret the helper uses."""

    def __init__(self, usage_id, uuid):
        self._usage_id = usage_id
        self._uuid = uuid

    def usageID(self):
        return self._usage_id

    def UUIDString(self):
        return self._uuid


class FakeConnection:
    """Recording stand-in for a libvirt connection."""

    def __init__(self, domains=(), secrets=(), uri="qemu:///system"):
        self.domains = list(domains)
        self.secrets = list(secrets)
        self.uri = uri
        self.closed = False
        self.defined = []
        # Raised by defineXMLFlags when set, to simulate invalid XML.
        self.define_error = None

    def close(self):
        self.closed = True

    def getURI(self):
        return self.uri

    def listAllDomains(self):
        return list(self.domains)

    def listAllSecrets(self):
        return list(self.secrets)

    def lookupByName(self, name):
        for domain in self.domains:
            if domain.name() == name:
                return domain
        raise KeyError(name)

    def defineXMLFlags(self, xml, flags):
        if self.define_error is not None:
            raise self.define_error
        self.defined.append((xml, flags))


class FakeLibvirt:
    """The libvirt module with open() replaced.

    Anything else, the VIR_DOMAIN_* constants and libvirtError included,
    falls through to the real module.
    """

    def __init__(self, conn):
        self.conn = conn
        self.uris = []

    def open(self, uri):
        self.uris.append(uri)
        return self.conn

    def __getattr__(self, name):
        return getattr(libvirt, name)


class FakeSubprocess:
    """The subprocess module with run() replaced.

    Anything else, CalledProcessError included, falls through to the
    real module.
    """

    def __init__(self):
        self.calls = []
        self.error = None

    def __getattr__(self, name):
        return getattr(subprocess, name)

    def run(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if self.error is not None:
            raise self.error

    @property
    def command(self):
        assert len(self.calls) == 1, "expected one run(), got {}".format(
            len(self.calls)
        )
        return self.calls[0][0]


@pytest.fixture
def conn():
    """A connection carrying one shut off domain."""
    return FakeConnection(domains=[FakeDomain()])


@pytest.fixture
def fake_libvirt(monkeypatch, conn):
    """Replace libvirt.open() as the helper module sees it."""
    fake = FakeLibvirt(conn)
    monkeypatch.setattr(libvirt_helper, "libvirt", fake)
    return fake


@pytest.fixture
def lvm(fake_libvirt):
    """A LibVirtManager on the fake connection."""
    return LibVirtManager()


@pytest.fixture
def virsh(monkeypatch):
    """Replace the subprocess module the helper calls virsh through."""
    fake = FakeSubprocess()
    monkeypatch.setattr(libvirt_helper, "subprocess", fake)
    return fake


def make_domain(name, state):
    """A domain reporting the given libvirt state."""
    return FakeDomain(name=name, state=state)


class TestConnection:
    """The connection the constructor opens, and closing it."""

    def test_the_default_uri(self, fake_libvirt):
        LibVirtManager()
        assert fake_libvirt.uris == ["qemu:///system"]

    def test_a_custom_uri(self, fake_libvirt):
        LibVirtManager("qemu+ssh://user@host/system")
        assert fake_libvirt.uris == ["qemu+ssh://user@host/system"]

    def test_close_closes_the_connection(self, lvm, conn):
        lvm.close()
        assert conn.closed is True

    def test_the_context_manager_yields_the_instance(self, fake_libvirt):
        with LibVirtManager() as manager:
            assert isinstance(manager, LibVirtManager)

    def test_leaving_the_context_closes(self, fake_libvirt, conn):
        with LibVirtManager():
            pass
        assert conn.closed is True


class TestList:
    """list() and list_uuids()."""

    def test_the_domain_names_are_returned(self, lvm):
        assert lvm.list() == [VM]

    def test_several_domains_are_listed(self, fake_libvirt, conn):
        conn.domains.append(FakeDomain(name="vm2"))
        assert LibVirtManager().list() == [VM, "vm2"]

    def test_no_domain_gives_an_empty_list(self, fake_libvirt, conn):
        conn.domains.clear()
        assert LibVirtManager().list() == []

    def test_uuids_are_mapped_to_their_domain(self, lvm):
        assert lvm.list_uuids() == {"uuid-1": VM}


class TestSecrets:
    """get_virsh_secrets(): the usage id to UUID mapping."""

    def test_the_secrets_are_mapped(self, fake_libvirt, conn):
        conn.secrets = [
            FakeSecret("client.libvirt secret", "uuid-a"),
            FakeSecret("other", "uuid-b"),
        ]
        assert LibVirtManager().get_virsh_secrets() == {
            "client.libvirt secret": "uuid-a",
            "other": "uuid-b",
        }

    def test_no_secret_gives_an_empty_dict(self, lvm):
        assert lvm.get_virsh_secrets() == {}


class TestDefine:
    """define(): validate and create a domain from XML."""

    XML = "<domain type='kvm'><name>vm1</name></domain>"

    def test_the_xml_is_passed_with_the_validate_flag(self, lvm, conn):
        lvm.define(self.XML)
        assert conn.defined == [(self.XML, libvirt.VIR_DOMAIN_DEFINE_VALIDATE)]

    def test_an_invalid_xml_is_reported(self, lvm, conn):
        conn.define_error = libvirt.libvirtError("invalid")
        with pytest.raises(libvirt.libvirtError):
            lvm.define(self.XML)

    def test_the_rejected_xml_is_logged(self, lvm, conn, caplog):
        conn.define_error = libvirt.libvirtError("invalid")
        with caplog.at_level("ERROR"):
            with pytest.raises(libvirt.libvirtError):
                lvm.define(self.XML)
        assert self.XML in caplog.text


class TestDomainActions:
    """The calls the helper forwards to a domain."""

    def test_undefine_asks_for_the_nvram_too(self, lvm, conn):
        lvm.undefine(VM)
        assert conn.domains[0].calls == [
            ("undefineFlags", libvirt.VIR_DOMAIN_UNDEFINE_NVRAM)
        ]

    def test_start_creates_the_domain(self, lvm, conn):
        lvm.start(VM)
        assert conn.domains[0].calls == ["create"]

    def test_stop_asks_for_a_shutdown(self, lvm, conn):
        lvm.stop(VM)
        assert conn.domains[0].calls == ["shutdown"]

    def test_force_stop_destroys_the_domain(self, lvm, conn):
        lvm.force_stop(VM)
        assert conn.domains[0].calls == ["destroy"]

    def test_autostart_is_enabled_as_one(self, lvm, conn):
        lvm.set_autostart(VM, True)
        assert conn.domains[0].autostart == 1

    def test_autostart_is_disabled_as_zero(self, lvm, conn):
        lvm.set_autostart(VM, False)
        assert conn.domains[0].autostart == 0


class TestStatus:
    """status(): the libvirt domain state translated to a word."""

    @pytest.mark.parametrize(
        "state, expected",
        [
            (libvirt.VIR_DOMAIN_NOSTATE, "Undefined"),
            (libvirt.VIR_DOMAIN_RUNNING, "Started"),
            (libvirt.VIR_DOMAIN_BLOCKED, "Paused"),
            (libvirt.VIR_DOMAIN_PAUSED, "Paused"),
            (libvirt.VIR_DOMAIN_SHUTDOWN, "Stopping"),
            (libvirt.VIR_DOMAIN_SHUTOFF, "Stopped"),
            (libvirt.VIR_DOMAIN_CRASHED, "FAILED"),
            (libvirt.VIR_DOMAIN_PMSUSPENDED, "Paused"),
        ],
    )
    def test_each_state_has_its_word(
        self, fake_libvirt, conn, state, expected
    ):
        conn.domains = [make_domain(VM, state)]
        assert LibVirtManager().status(VM) == expected

    def test_an_unknown_state_reads_as_undefined(self, fake_libvirt, conn):
        conn.domains = [make_domain(VM, 999)]
        assert LibVirtManager().status(VM) == "Undefined"

    def test_a_domain_that_does_not_exist(self, lvm):
        assert lvm.status("absent") == "Undefined"

    def test_the_missing_domain_is_logged(self, lvm, caplog):
        with caplog.at_level("INFO", logger=libvirt_helper.logger.name):
            lvm.status("absent")
        assert "does not exist" in caplog.text


class TestConsole:
    """console(): hand the terminal over to virsh."""

    def test_the_command_targets_the_domain_on_the_uri(self, lvm, virsh):
        lvm.console(VM)
        assert virsh.command == [
            "/usr/bin/virsh",
            "-c",
            "qemu:///system",
            "console",
            VM,
        ]

    def test_the_connection_uri_is_used(self, fake_libvirt, conn, virsh):
        conn.uri = "qemu+ssh://user@hyp1/system"
        LibVirtManager().console(VM)
        assert virsh.command[2] == "qemu+ssh://user@hyp1/system"

    def test_the_standard_streams_are_passed_through(self, lvm, virsh):
        lvm.console(VM)
        kwargs = virsh.calls[0][1]
        assert kwargs["stdin"] is not None
        assert kwargs["stdout"] is not None
        assert kwargs["stderr"] is not None

    def test_a_virsh_failure_is_swallowed(self, lvm, virsh):
        virsh.error = subprocess.CalledProcessError(1, "virsh")
        lvm.console(VM)

    def test_the_command_is_logged(self, lvm, virsh, caplog):
        with caplog.at_level("DEBUG", logger=libvirt_helper.logger.name):
            lvm.console(VM)
        assert "/usr/bin/virsh -c qemu:///system console " + VM in caplog.text


class TestExportConfiguration:
    """export_configuration(): dump the XML through a shell redirection."""

    def test_the_dump_is_redirected_to_the_path(self, virsh):
        LibVirtManager.export_configuration(VM, "/tmp/vm1.xml")
        assert virsh.command == (
            "/usr/bin/virsh -c 'qemu:///system' dumpxml vm1 > /tmp/vm1.xml"
        )

    def test_it_runs_through_a_shell(self, virsh):
        LibVirtManager.export_configuration(VM, "/tmp/vm1.xml")
        assert virsh.calls[0][1]["shell"] is True

    def test_a_failure_is_not_swallowed(self, virsh):
        LibVirtManager.export_configuration(VM, "/tmp/vm1.xml")
        assert virsh.calls[0][1]["check"] is True
