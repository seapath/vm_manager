# Copyright (C) 2026, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""
Unit tests for the Pacemaker helper, with no cluster.

Every call the helper makes goes through the subprocess module, so that
module is the only seam these tests need: the recording fake below
replaces it inside vm_manager.helpers.pacemaker. The fake exposes only
what the helper is expected to use, so an unexpected call fails with an
AttributeError instead of quietly returning a Mock.

Assertions are on the argument list handed to subprocess, because that
list is the helper's whole contract with crm.

The tests that drive a real cluster live in
vm_manager/helpers/tests/pacemaker/ and are run by hand.
"""

import subprocess

import pytest

from vm_manager.helpers import pacemaker
from vm_manager.helpers.pacemaker import Pacemaker, PacemakerException

RESOURCE = "vm1"

# A resource line as "crm resource status" prints it, tab separated.
RESOURCE_LINE = "  * {}\t(ocf::seapath:VirtualDomain):\t Started hyp1"


class FakeCompletedProcess:
    """What subprocess.run() gives back."""

    def __init__(self, stdout=b"", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


class FakePopen:
    """What subprocess.Popen() gives back, for is_valid_host()."""

    def __init__(self, returncode):
        self.returncode = returncode
        self.waited = False

    def wait(self):
        self.waited = True
        return self.returncode


class FakeSubprocess:
    """Recording stand-in for the subprocess module.

    list2cmdline is the real one on purpose: it only builds log lines,
    and a stub would hide what those lines say.
    """

    PIPE = subprocess.PIPE
    list2cmdline = staticmethod(subprocess.list2cmdline)

    def __init__(self):
        self.calls = []
        # What the next run() reports back.
        self.stdout = b""
        self.returncode = 0
        # How many run() calls a test allows before declaring the helper
        # stuck. wait_for() polls, so without a budget a broken countdown
        # would hang the suite instead of failing it.
        self.call_budget = None

    def run(self, args, **kwargs):
        self.calls.append(("run", args, kwargs))
        if self.call_budget is not None and len(self.calls) > self.call_budget:
            raise AssertionError(
                "run() called {} times, budget was {}: the helper is "
                "looping".format(len(self.calls), self.call_budget)
            )
        return FakeCompletedProcess(self.stdout, self.returncode)

    def Popen(self, command, **kwargs):
        self.calls.append(("Popen", command, kwargs))
        self.popen = FakePopen(self.returncode)
        return self.popen

    @property
    def commands(self):
        """Every argument list handed to run(), in order."""
        return [call[1] for call in self.calls if call[0] == "run"]

    @property
    def command(self):
        """The argument list of the single run() the helper made."""
        assert len(self.commands) == 1, "expected one run(), got {}".format(
            len(self.commands)
        )
        return self.commands[0]

    @property
    def kwargs(self):
        """The keyword arguments of the single run() the helper made."""
        runs = [call for call in self.calls if call[0] == "run"]
        assert len(runs) == 1, "expected one run(), got {}".format(len(runs))
        return runs[0][2]


@pytest.fixture
def crm(monkeypatch):
    """Replace the subprocess module the helper talks to."""
    fake = FakeSubprocess()
    monkeypatch.setattr(pacemaker, "subprocess", fake)
    return fake


@pytest.fixture
def p(crm):
    """A Pacemaker bound to RESOURCE, with subprocess already faked."""
    return Pacemaker(RESOURCE)


def status_output(*lines):
    """Build a "crm resource status" output from resource lines."""
    return ("\n".join(lines) + "\n").encode()


class TestResource:
    """The resource the instance is bound to."""

    def test_the_constructor_sets_it(self, p):
        assert p.get_resource() == RESOURCE

    def test_the_setter_replaces_it(self, p):
        p.set_resource("vm2")
        assert p.get_resource() == "vm2"

    def test_the_context_manager_yields_the_instance(self, p):
        with p as entered:
            assert entered is p

    def test_the_context_is_logged(self, p, caplog):
        with caplog.at_level("INFO", logger=pacemaker.logger.name):
            with p:
                pass
        assert "Start context" in caplog.text
        assert "Exiting context" in caplog.text


class TestCrmResourceCommands:
    """start, stop, restart and cleanup, all built the same way."""

    @pytest.mark.parametrize(
        "method, verb",
        [
            ("start", "start"),
            ("stop", "stop"),
            ("restart", "restart"),
            ("cleanup", "cleanup"),
        ],
    )
    def test_the_verb_and_the_resource_are_passed(self, p, crm, method, verb):
        getattr(p, method)()
        assert crm.command == ["crm", "resource", verb, RESOURCE]

    def test_a_failure_is_not_swallowed(self, p, crm):
        p.start()
        assert crm.kwargs["check"] is True

    def test_the_command_is_logged(self, p, crm, caplog):
        with caplog.at_level("INFO", logger=pacemaker.logger.name):
            p.start()
        assert "crm resource start vm1" in caplog.text


class TestForceStop:
    """force_stop(): crm_resource, bypassing the cluster."""

    def test_the_command_targets_the_resource(self, p, crm):
        p.force_stop()
        assert crm.command == [
            "crm_resource",
            "--force-stop",
            "--resource",
            RESOURCE,
        ]

    def test_a_failure_is_not_swallowed(self, p, crm):
        p.force_stop()
        assert crm.kwargs["check"] is True


class TestListResources:
    """list_resources(): the VirtualDomain resources crm reports."""

    def test_the_resource_names_are_extracted(self, crm):
        crm.stdout = status_output(
            RESOURCE_LINE.format("vm1"), RESOURCE_LINE.format("vm2")
        )
        assert Pacemaker.list_resources() == ["vm1", "vm2"]

    def test_a_single_colon_ocf_is_matched_too(self, crm):
        crm.stdout = status_output(
            "  * vm1\t(ocf:seapath:VirtualDomain):\t Started hyp1"
        )
        assert Pacemaker.list_resources() == ["vm1"]

    def test_other_resources_are_ignored(self, crm):
        crm.stdout = status_output(
            "  * fence1\t(stonith:fence_ipmilan):\t Started hyp1",
            RESOURCE_LINE.format("vm1"),
        )
        assert Pacemaker.list_resources() == ["vm1"]

    def test_an_empty_cluster_gives_an_empty_list(self, crm):
        crm.stdout = b"NO resources configured\n"
        assert Pacemaker.list_resources() == []

    def test_the_other_empty_wording_is_handled(self, crm):
        crm.stdout = b"No resources\n"
        assert Pacemaker.list_resources() == []

    def test_a_crm_failure_is_tolerated(self, crm):
        Pacemaker.list_resources()
        assert crm.kwargs["check"] is False


class TestShow:
    """show(): the state crm reports for this resource."""

    def test_the_state_is_returned(self, p, crm):
        crm.stdout = status_output(RESOURCE_LINE.format("vm1"))
        assert p.show() == "Started hyp1"

    def test_another_resource_is_not_reported(self, p, crm):
        crm.stdout = status_output(RESOURCE_LINE.format("vm2"))
        assert p.show() is None

    def test_a_line_with_the_wrong_shape_is_skipped(self, p, crm):
        crm.stdout = status_output(
            "  * vm1\t(ocf::seapath:VirtualDomain): Started hyp1",
            RESOURCE_LINE.format("vm1"),
        )
        assert p.show() == "Started hyp1"

    def test_no_resource_at_all_gives_none(self, p, crm):
        crm.stdout = b"NO resources configured\n"
        assert p.show() is None


class TestStatus:
    """status(): the cluster status, printed rather than parsed."""

    def test_the_command_is_crm_status(self, crm):
        Pacemaker.status()
        assert crm.command == ["crm", "status"]


class TestDelete:
    """delete(): drop the resource, optionally cleaning it first."""

    def test_the_plain_delete(self, p, crm):
        p.delete()
        assert crm.command == ["crm", "configure", "delete", RESOURCE]

    def test_force_adds_the_flag_before_the_resource(self, p, crm):
        p.delete(force=True)
        assert crm.command == [
            "crm",
            "configure",
            "delete",
            "--force",
            RESOURCE,
        ]

    def test_clean_runs_first(self, p, crm):
        p.delete(clean=True)
        assert crm.commands == [
            ["crm", "resource", "clean"],
            ["crm", "configure", "delete", RESOURCE],
        ]

    def test_clean_and_force_together(self, p, crm):
        p.delete(force=True, clean=True)
        assert crm.commands[0] == ["crm", "resource", "clean"]
        assert "--force" in crm.commands[1]


class TestManage:
    """manage(): hand the resource back to the cluster."""

    def test_the_command_targets_the_resource(self, p, crm):
        p.manage()
        assert crm.command == ["crm", "resource", "manage", RESOURCE]


class TestLocations:
    """The three location constraints."""

    def test_disable_location_bans_the_node(self, p, crm):
        p.disable_location("hyp1")
        assert crm.command == ["crm", "resource", "ban", RESOURCE, "hyp1"]

    def test_pin_location_names_the_constraint(self, p, crm):
        p.pin_location("hyp1")
        assert crm.command == [
            "crm",
            "configure",
            "location",
            "pin-vm1-onhyp1",
            RESOURCE,
            "resource-discovery=exclusive",
            "inf:",
            "hyp1",
        ]

    def test_default_location_moves_the_resource(self, p, crm):
        p.default_location("hyp1")
        assert crm.command == ["crm", "resource", "move", RESOURCE, "hyp1"]


class TestAddColocation:
    """add_colocation(): group the resource with others."""

    def test_at_least_one_resource_is_required(self, p, crm):
        with pytest.raises(Exception, match="At least one resource"):
            p.add_colocation()
        assert crm.calls == []

    def test_a_weak_colocation_scores_700(self, p, crm):
        p.add_colocation("res1")
        assert crm.command == [
            "crm",
            "configure",
            "colocation",
            "colocation-vm1-withres1",
            "700:",
            RESOURCE,
            "(",
            "res1",
            ")",
        ]

    def test_a_strong_colocation_scores_inf(self, p, crm):
        p.add_colocation("res1", strong=True)
        assert crm.command[3] == "colocation-strong-vm1-withres1"
        assert crm.command[4] == "inf:"

    def test_several_resources_are_joined_in_the_name(self, p, crm):
        p.add_colocation("res1", "res2")
        assert crm.command[3] == "colocation-vm1-withres1-res2"
        assert crm.command[-3:] == ["res1", "res2", ")"]


class TestWaitFor:
    """wait_for(): poll show() until the state matches."""

    def test_it_returns_once_the_state_is_reached(self, p, crm):
        crm.stdout = status_output(RESOURCE_LINE.format("vm1"))
        p.wait_for("Started hyp1", periods=0.001, nb_periods=10)

    def test_it_gives_up_after_nb_periods(self, p, crm):
        crm.stdout = status_output(RESOURCE_LINE.format("vm2"))
        crm.call_budget = 10
        with pytest.raises(PacemakerException, match="Timeout"):
            p.wait_for("Started hyp1", periods=0.001, nb_periods=2)

    def test_it_polls_until_it_gives_up(self, p, crm):
        crm.stdout = status_output(RESOURCE_LINE.format("vm2"))
        crm.call_budget = 10
        with pytest.raises(PacemakerException):
            p.wait_for("Started hyp1", periods=0.001, nb_periods=3)
        assert len(crm.commands) == 3


class TestRunCrmCmd:
    """run_crm_cmd(): an arbitrary crm configure command."""

    def test_the_command_is_split_on_spaces(self, p, crm):
        p.run_crm_cmd("property maintenance-mode=true")
        assert crm.command == [
            "crm",
            "configure",
            "property",
            "maintenance-mode=true",
        ]

    def test_an_empty_command_runs_nothing(self, p, crm):
        p.run_crm_cmd("")
        assert crm.calls == []

    def test_none_runs_nothing(self, p, crm):
        p.run_crm_cmd(None)
        assert crm.calls == []


class TestMeta:
    """add_meta() and remove_meta()."""

    def test_a_meta_is_set(self, p, crm):
        p.add_meta("remote-node", "remote1")
        assert crm.command == [
            "crm",
            "resource",
            "meta",
            RESOURCE,
            "set",
            "remote-node",
            "remote1",
        ]

    def test_a_meta_is_deleted(self, p, crm):
        p.remove_meta("remote-node")
        assert crm.command == [
            "crm",
            "resource",
            "meta",
            RESOURCE,
            "delete",
            "remote-node",
        ]


class TestIsValidHost:
    """is_valid_host(): grep the host in "crm node server"."""

    def test_a_known_host(self, crm):
        crm.returncode = 0
        assert Pacemaker.is_valid_host("hyp1") is True

    def test_an_unknown_host(self, crm):
        crm.returncode = 1
        assert Pacemaker.is_valid_host("nowhere") is False

    def test_the_host_is_anchored_in_the_grep(self, crm):
        Pacemaker.is_valid_host("hyp1")
        assert "^hyp1$" in crm.calls[0][1]

    def test_the_process_is_waited_for(self, crm):
        Pacemaker.is_valid_host("hyp1")
        assert crm.popen.waited is True


class TestFindResource:
    """find_resource(): the node a resource runs on."""

    def test_the_host_is_returned(self, crm):
        crm.stdout = b"hyp1\n"
        assert Pacemaker.find_resource(RESOURCE) == "hyp1"

    def test_a_resource_running_nowhere_gives_none(self, crm):
        crm.stdout = b"\n"
        assert Pacemaker.find_resource(RESOURCE) is None

    def test_the_resource_is_anchored_in_the_grep(self, crm):
        Pacemaker.find_resource(RESOURCE)
        assert r"^  \* vm1\b" in crm.command

    def test_the_lookup_is_logged(self, crm, caplog):
        crm.stdout = b"hyp1\n"
        with caplog.at_level("DEBUG", logger=pacemaker.logger.name):
            Pacemaker.find_resource(RESOURCE)
        assert "found on hyp1" in caplog.text

    def test_a_miss_is_logged(self, crm, caplog):
        with caplog.at_level("DEBUG", logger=pacemaker.logger.name):
            Pacemaker.find_resource(RESOURCE)
        assert "not found" in caplog.text


class TestAddVm:
    """add_vm(): the crm configure primitive command, built by hand."""

    XML = "/etc/libvirt/qemu/vm1.xml"

    DEFAULT = [
        "crm",
        "configure",
        "primitive",
        RESOURCE,
        "ocf:seapath:VirtualDomain",
        "params",
        "force_stop=false",
        "migration_downtime=0",
        "config=" + XML,
        "hypervisor='qemu:///system'",
        "seapath='false'",
        "migration_transport=ssh",
        "migration_user='root'",
        "meta",
        "allow-migrate='false'",
        "is-managed=true",
        "priority='0'",
        "target-role=Started",
        "op",
        "start",
        "timeout='120'",
        "op",
        "stop",
        "timeout='30'",
        "op",
        "migrate_from",
        "timeout='60'",
        "op",
        "migrate_to",
        "timeout='120'",
        "op",
        "monitor",
        "timeout='60'",
        "interval='10'",
    ]

    def add(self, p, **options):
        """Call add_vm with the XML every option set needs."""
        nostart = options.pop("nostart", False)
        options.setdefault("xml", self.XML)
        p.add_vm(options, nostart=nostart)

    def test_the_default_command(self, p, crm):
        self.add(p)
        assert crm.command == self.DEFAULT

    def test_the_xml_path_is_required(self, p):
        with pytest.raises(KeyError):
            p.add_vm({})

    def test_nostart_asks_for_a_stopped_role(self, p, crm):
        self.add(p, nostart=True)
        assert "target-role=Stopped" in crm.command
        assert "target-role=Started" not in crm.command

    @pytest.mark.parametrize(
        "option, value, expected",
        [
            ("force_stop", True, "force_stop=true"),
            ("seapath_managed", True, "seapath='true'"),
            ("live_migration", True, "allow-migrate='true'"),
            ("is_managed", False, "is-managed=false"),
            ("migration_downtime", 500, "migration_downtime=500"),
            (
                "migration_user",
                "libvirtadmin",
                "migration_user='libvirtadmin'",
            ),
            ("priority", "10", "priority='10'"),
            ("start_timeout", "300", "timeout='300'"),
            ("monitor_interval", "20", "interval='20'"),
        ],
    )
    def test_an_option_reaches_the_command(
        self, p, crm, option, value, expected
    ):
        self.add(p, **{option: value})
        assert expected in crm.command

    def test_custom_params_land_in_the_params_section(self, p, crm):
        self.add(p, custom_params={"key1": "value1"})
        assert crm.command.index("key1='value1'") < crm.command.index("meta")

    def test_custom_meta_lands_in_the_meta_section(self, p, crm):
        self.add(p, custom_meta={"key1": "value1"})
        index = crm.command.index("key1='value1'")
        assert crm.command.index("meta") < index < crm.command.index("op")

    def test_custom_utilization_is_appended(self, p, crm):
        self.add(p, custom_utilization={"cpu": "2"})
        assert crm.command[-2:] == ["utilization", "cpu='2'"]

    def test_no_utilization_section_without_the_option(self, p, crm):
        self.add(p)
        assert "utilization" not in crm.command

    def test_a_pacemaker_remote_is_declared_last(self, p, crm):
        self.add(p, pacemaker_remote="remote1")
        assert crm.command[-2:] == ["meta", "remote-node='remote1'"]

    def test_the_remote_address_port_and_timeout(self, p, crm):
        self.add(
            p,
            pacemaker_remote="remote1",
            pacemaker_remote_addr="10.0.0.1",
            pacemaker_remote_port="3121",
            pacemaker_remote_timeout="60",
        )
        assert crm.command[-5:] == [
            "meta",
            "remote-node='remote1'",
            "remote-addr='10.0.0.1'",
            "remote-port='3121'",
            "remote-connect-timeout='60'",
        ]

    def test_the_remote_extras_are_each_optional(self, p, crm):
        self.add(p, pacemaker_remote="remote1", pacemaker_remote_port="3121")
        assert "remote-port='3121'" in crm.command
        assert not [a for a in crm.command if a.startswith("remote-addr")]
        assert not [
            a for a in crm.command if a.startswith("remote-connect-timeout")
        ]

    def test_no_remote_section_without_the_option(self, p, crm):
        self.add(p)
        assert not [a for a in crm.command if a.startswith("remote-")]

    def test_the_command_is_logged(self, p, crm, caplog):
        with caplog.at_level("INFO", logger=pacemaker.logger.name):
            self.add(p)
        assert "crm configure primitive vm1" in caplog.text
