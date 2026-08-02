# Copyright (C) 2026, Sprecher Automation
# Copyright (C) 2026, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""
Unit tests for the vm_manager_cmd CLI.

These tests cover the argparse layer and the main() dispatch table with
every vm_manager entry point replaced by a recorder, so nothing here
touches libvirt, Ceph or Pacemaker. The end-to-end test that drives
main() through the real backend lives in test_vm_manager_cmd_cluster.py
(which CI ignores because it needs a real cluster).

The cluster subcommands are only registered when vm_manager starts in
cluster mode; tests/conftest.py arranges for that to be true even without
Ceph installed.
"""

import argparse
import datetime
import logging
import sys

import pytest

import vm_manager
from vm_manager import vm_manager_cmd
from vm_manager.vm_manager_cmd import ParseMetaData, get_parser

pytestmark = pytest.mark.skipif(
    not vm_manager.cluster_mode,
    reason="the cluster subcommands are only registered in cluster mode",
)


# Every vm_manager entry point main() may call, with the value the fake
# should return for the commands whose result main() prints.
API_RESULTS = {
    "add_colocation": None,
    "add_pacemaker_remote": None,
    "add_to_cluster": None,
    "clone": None,
    "console": None,
    "create": None,
    "create_snapshot": None,
    "disable_vm": None,
    "enable_vm": None,
    "get_metadata": "some-value",
    "list_metadata": ["key1", "key2"],
    "list_snapshots": ["snap1", "snap2"],
    "list_vms": ["vm1", "vm2"],
    "purge_image": None,
    "remove": None,
    "remove_pacemaker_remote": None,
    "remove_snapshot": None,
    "rollback_snapshot": None,
    "set_metadata": None,
    "start": None,
    "status": "Running",
    "stop": None,
}


# One minimally valid command line per registered subcommand.
MINIMAL_ARGV = {
    "add-to-cluster": ["add-to-cluster", "-n", "vm1"],
    "add_colocation": ["add_colocation", "-n", "vm1", "other"],
    "add_pacemaker_remote": [
        "add_pacemaker_remote",
        "-n",
        "vm1",
        "--remote_name",
        "remote1",
        "--remote_address",
        "10.0.0.1",
    ],
    "clone": ["clone", "-n", "vm1", "--dst_name", "vm2"],
    "console": ["console", "vm1"],
    "create_snapshot": ["create_snapshot", "-n", "vm1", "--snap_name", "s1"],
    "disable": ["disable", "-n", "vm1"],
    "enable": ["enable", "-n", "vm1"],
    "get_metadata": ["get_metadata", "-n", "vm1", "--metadata_name", "k"],
    "list": ["list"],
    "list_metadata": ["list_metadata", "-n", "vm1"],
    "list_snapshots": ["list_snapshots", "-n", "vm1"],
    "purge": ["purge", "-n", "vm1"],
    "remove": ["remove", "-n", "vm1"],
    "remove_pacemaker_remote": ["remove_pacemaker_remote", "-n", "vm1"],
    "remove_snapshot": ["remove_snapshot", "-n", "vm1", "--snap_name", "s1"],
    "rollback": ["rollback", "-n", "vm1", "--snap_name", "s1"],
    "set_metadata": [
        "set_metadata",
        "-n",
        "vm1",
        "--metadata_name",
        "k",
        "--metadata_value",
        "v",
    ],
    "start": ["start", "-n", "vm1"],
    "status": ["status", "-n", "vm1"],
    "stop": ["stop", "-n", "vm1"],
}


BASE_CREATE_ARGS = [
    "create",
    "--name",
    "vm1",
    "--xml",
    "/nonexistent/vm.xml",
    "-i",
    "/nonexistent/sys.qcow2",
]


class ApiRecorder:
    """Records the vm_manager calls made by main()."""

    def __init__(self):
        self.calls = []

    def install(self, monkeypatch):
        for name, result in API_RESULTS.items():
            monkeypatch.setattr(vm_manager, name, self._make(name, result))

    def _make(self, name, result):
        def recorder(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return result

        return recorder

    @property
    def only(self):
        """Return the single recorded call, failing if there is not exactly one.

        main() dispatches one command per invocation, so a test that gets
        anything else is testing something it did not mean to.
        """
        assert len(self.calls) == 1, "expected one call, got {}".format(
            self.calls
        )
        return self.calls[0]


@pytest.fixture
def parser():
    return get_parser()


@pytest.fixture
def api(monkeypatch):
    """Replace every vm_manager entry point with a recorder."""
    recorder = ApiRecorder()
    recorder.install(monkeypatch)
    return recorder


@pytest.fixture
def run_cli(monkeypatch):
    """Run main() with the given arguments."""

    def run(*argv):
        monkeypatch.setattr(sys, "argv", ["vm_manager_cmd"] + list(argv))
        vm_manager_cmd.main()

    return run


@pytest.fixture
def xml_file(tmp_path):
    """Write a minimal libvirt XML file and return its path."""
    path = tmp_path / "vm.xml"
    path.write_text("<domain type='kvm'><name>template</name></domain>")
    return str(path)


class TestParseMetaData:
    """The custom argparse action behind --metadata and --pacemaker-*."""

    def test_single_pair(self, parser):
        args = parser.parse_args(
            BASE_CREATE_ARGS + ["--metadata", "role=router"]
        )
        assert args.metadata == {"role": "router"}

    def test_several_pairs_in_one_flag(self, parser):
        args = parser.parse_args(
            BASE_CREATE_ARGS + ["--metadata", "role=router", "site=paris"]
        )
        assert args.metadata == {"role": "router", "site": "paris"}

    def test_repeated_flag_accumulates(self, parser):
        args = parser.parse_args(
            BASE_CREATE_ARGS
            + ["--metadata", "role=router", "--metadata", "site=paris"]
        )
        assert args.metadata == {"role": "router", "site": "paris"}

    def test_repeated_key_takes_the_last_value(self, parser):
        args = parser.parse_args(
            BASE_CREATE_ARGS + ["--metadata", "role=router", "role=switch"]
        )
        assert args.metadata == {"role": "switch"}

    def test_value_may_contain_equal_signs(self, parser):
        """Only the first '=' separates, so values can carry their own."""
        args = parser.parse_args(
            BASE_CREATE_ARGS + ["--metadata", "cmdline=root=/dev/sda1 ro"]
        )
        assert args.metadata == {"cmdline": "root=/dev/sda1 ro"}

    def test_empty_value_is_kept(self, parser):
        args = parser.parse_args(BASE_CREATE_ARGS + ["--metadata", "role="])
        assert args.metadata == {"role": ""}

    def test_omitted_flag_defaults_to_none(self, parser):
        args = parser.parse_args(BASE_CREATE_ARGS)
        assert args.metadata is None

    def test_pair_without_equal_sign_raises(self, parser):
        with pytest.raises(ValueError):
            parser.parse_args(BASE_CREATE_ARGS + ["--metadata", "role"])

    def test_pacemaker_flags_use_separate_dicts(self, parser):
        args = parser.parse_args(
            BASE_CREATE_ARGS
            + [
                "--metadata",
                "a=1",
                "--pacemaker-meta",
                "b=2",
                "--pacemaker-params",
                "c=3",
                "--pacemaker-utilization",
                "d=4",
            ]
        )
        assert args.metadata == {"a": "1"}
        assert args.pacemaker_meta == {"b": "2"}
        assert args.pacemaker_params == {"c": "3"}
        assert args.pacemaker_utilization == {"d": "4"}

    def test_action_creates_the_dict_when_absent(self):
        action = ParseMetaData(option_strings=["--metadata"], dest="metadata")
        namespace = argparse.Namespace()
        action(None, namespace, ["a=1"])
        assert namespace.metadata == {"a": "1"}

    def test_action_with_no_values_yields_empty_dict(self):
        action = ParseMetaData(option_strings=["--metadata"], dest="metadata")
        namespace = argparse.Namespace()
        action(None, namespace, [])
        assert namespace.metadata == {}


class TestParserStructure:
    """Which subcommands exist and which arguments they require."""

    @pytest.mark.parametrize("argv", MINIMAL_ARGV.values(), ids=MINIMAL_ARGV)
    def test_minimal_invocation_parses(self, parser, argv):
        args = parser.parse_args(argv)
        assert args.command == argv[0]

    @pytest.mark.parametrize(
        "argv",
        [a for name, a in MINIMAL_ARGV.items() if name not in ("list",)],
        ids=[n for n in MINIMAL_ARGV if n not in ("list",)],
    )
    def test_every_subcommand_but_list_names_a_vm(self, parser, argv):
        """console takes the name positionally, the rest take -n/--name."""
        args = parser.parse_args(argv)
        assert args.name == "vm1"

    @pytest.mark.parametrize(
        "argv",
        [
            ["start"],
            ["stop"],
            ["remove"],
            ["status"],
            ["enable"],
            ["disable"],
        ],
    )
    def test_missing_name_is_rejected(self, parser, argv):
        with pytest.raises(SystemExit) as excinfo:
            parser.parse_args(argv)
        assert excinfo.value.code == 2

    def test_no_command_is_rejected(self, parser):
        with pytest.raises(SystemExit) as excinfo:
            parser.parse_args([])
        assert excinfo.value.code == 2

    def test_unknown_command_is_rejected(self, parser):
        with pytest.raises(SystemExit) as excinfo:
            parser.parse_args(["teleport", "-n", "vm1"])
        assert excinfo.value.code == 2

    def test_create_requires_xml_and_image(self, parser):
        with pytest.raises(SystemExit):
            parser.parse_args(["create", "-n", "vm1"])

    def test_clone_requires_dst_name(self, parser):
        with pytest.raises(SystemExit):
            parser.parse_args(["clone", "-n", "vm1"])

    def test_console_rejects_the_name_flag(self, parser):
        """console takes its name positionally, not through -n."""
        with pytest.raises(SystemExit):
            parser.parse_args(["console", "-n", "vm1"])

    def test_console_ssh_user_defaults_to_libvirtadmin(self, parser):
        args = parser.parse_args(["console", "vm1"])
        assert args.ssh_user == "libvirtadmin"

    def test_disk_bus_defaults_to_virtio(self, parser):
        args = parser.parse_args(BASE_CREATE_ARGS)
        assert args.disk_bus == "virtio"

    def test_verbose_defaults_to_false(self, parser):
        args = parser.parse_args(BASE_CREATE_ARGS)
        assert args.verbose is False

    def test_autostart_is_not_registered_in_cluster_mode(self, parser):
        """autostart is a standalone-only command."""
        with pytest.raises(SystemExit):
            parser.parse_args(["autostart", "-n", "vm1", "--enable"])

    def test_purge_date_is_parsed(self, parser):
        args = parser.parse_args(
            ["purge", "-n", "vm1", "--date", "20/04/2021 14:02:32"]
        )
        assert args.date == datetime.datetime(2021, 4, 20, 14, 2, 32)

    def test_purge_rejects_a_malformed_date(self, parser):
        with pytest.raises(SystemExit):
            parser.parse_args(["purge", "-n", "vm1", "--date", "2021-04-20"])

    def test_purge_number_is_an_int(self, parser):
        args = parser.parse_args(["purge", "-n", "vm1", "--number", "3"])
        assert args.number == 3

    def test_add_colocation_takes_several_resources(self, parser):
        args = parser.parse_args(["add_colocation", "-n", "vm1", "a", "b"])
        assert args.resources == ["a", "b"]

    def test_add_colocation_requires_a_resource(self, parser):
        with pytest.raises(SystemExit):
            parser.parse_args(["add_colocation", "-n", "vm1"])


class TestCreateAdditionalDiskFlag:
    def test_single_additional_disk_parses_to_list(self, parser):
        args = parser.parse_args(
            BASE_CREATE_ARGS + ["--additional-disk", "/nonexistent/a.qcow2"]
        )
        assert args.additional_disks == ["/nonexistent/a.qcow2"]

    def test_multiple_additional_disks_accumulate_in_order(self, parser):
        args = parser.parse_args(
            BASE_CREATE_ARGS
            + [
                "--additional-disk",
                "/nonexistent/a.qcow2",
                "--additional-disk",
                "/nonexistent/b.qcow2",
                "--additional-disk",
                "/nonexistent/c.qcow2",
            ]
        )
        assert args.additional_disks == [
            "/nonexistent/a.qcow2",
            "/nonexistent/b.qcow2",
            "/nonexistent/c.qcow2",
        ]

    def test_omitted_flag_defaults_to_none(self, parser):
        args = parser.parse_args(BASE_CREATE_ARGS)
        assert args.additional_disks is None

    def test_additional_disk_singular_attr_not_used(self, parser):
        """Guard against accidentally dropping dest= - without it,
        argparse would derive args.additional_disk (singular) and the
        backend would never see the list.
        """
        args = parser.parse_args(
            BASE_CREATE_ARGS + ["--additional-disk", "/nonexistent/a.qcow2"]
        )
        assert not hasattr(args, "additional_disk")


# Command line, then the (function, args, kwargs) main() is expected to
# forward it to. Only the commands taking positional arguments are listed
# here; create, clone and add-to-cluster pass a whole dict and get their
# own tests below.
DISPATCH_CASES = [
    (["list"], ("list_vms", (), {})),
    (["start", "-n", "vm1"], ("start", ("vm1",), {})),
    (["stop", "-n", "vm1"], ("stop", ("vm1",), {"force": False})),
    (["stop", "-n", "vm1", "-f"], ("stop", ("vm1",), {"force": True})),
    (["stop", "-n", "vm1", "--force"], ("stop", ("vm1",), {"force": True})),
    (["remove", "-n", "vm1"], ("remove", ("vm1",), {})),
    (["status", "-n", "vm1"], ("status", ("vm1",), {})),
    (["disable", "-n", "vm1"], ("disable_vm", ("vm1",), {})),
    (["enable", "-n", "vm1"], ("enable_vm", ("vm1", False), {})),
    (["enable", "-n", "vm1", "--nostart"], ("enable_vm", ("vm1", True), {})),
    (["console", "vm1"], ("console", ("vm1", "libvirtadmin"), {})),
    (
        ["console", "vm1", "--ssh-user", "root"],
        ("console", ("vm1", "root"), {}),
    ),
    (
        ["create_snapshot", "-n", "vm1", "--snap_name", "s1"],
        ("create_snapshot", ("vm1", "s1"), {}),
    ),
    (
        ["remove_snapshot", "-n", "vm1", "--snap_name", "s1"],
        ("remove_snapshot", ("vm1", "s1"), {}),
    ),
    (["list_snapshots", "-n", "vm1"], ("list_snapshots", ("vm1",), {})),
    (
        ["rollback", "-n", "vm1", "--snap_name", "s1"],
        ("rollback_snapshot", ("vm1", "s1"), {}),
    ),
    (["purge", "-n", "vm1"], ("purge_image", ("vm1", None, None), {})),
    (
        ["purge", "-n", "vm1", "--number", "3"],
        ("purge_image", ("vm1", None, 3), {}),
    ),
    (["list_metadata", "-n", "vm1"], ("list_metadata", ("vm1",), {})),
    (
        ["get_metadata", "-n", "vm1", "--metadata_name", "k"],
        ("get_metadata", ("vm1", "k"), {}),
    ),
    (
        [
            "set_metadata",
            "-n",
            "vm1",
            "--metadata_name",
            "k",
            "--metadata_value",
            "v",
        ],
        ("set_metadata", ("vm1", "k", "v"), {}),
    ),
    (
        ["add_colocation", "-n", "vm1", "a", "b"],
        ("add_colocation", ("vm1", "a", "b"), {"strong": False}),
    ),
    (
        ["add_colocation", "-n", "vm1", "a", "--strong"],
        ("add_colocation", ("vm1", "a"), {"strong": True}),
    ),
    (
        ["remove_pacemaker_remote", "-n", "vm1"],
        ("remove_pacemaker_remote", ("vm1",), {}),
    ),
    (
        [
            "add_pacemaker_remote",
            "-n",
            "vm1",
            "--remote_name",
            "r1",
            "--remote_address",
            "10.0.0.1",
        ],
        (
            "add_pacemaker_remote",
            ("vm1", "r1", "10.0.0.1"),
            {"remote_node_port": None, "remote_node_timeout": None},
        ),
    ),
    (
        [
            "add_pacemaker_remote",
            "-n",
            "vm1",
            "--remote_name",
            "r1",
            "--remote_address",
            "10.0.0.1",
            "--remote_port",
            "3121",
            "--remote_timeout",
            "60",
        ],
        (
            "add_pacemaker_remote",
            ("vm1", "r1", "10.0.0.1"),
            {"remote_node_port": "3121", "remote_node_timeout": "60"},
        ),
    ),
]


class TestMainDispatch:
    @pytest.mark.parametrize(
        "argv,expected",
        DISPATCH_CASES,
        ids=[" ".join(argv) for argv, _ in DISPATCH_CASES],
    )
    def test_command_reaches_the_right_entry_point(
        self, run_cli, api, argv, expected
    ):
        run_cli(*argv)
        assert api.only == expected

    def test_list_prints_one_vm_per_line(self, run_cli, api, capsys):
        run_cli("list")
        assert capsys.readouterr().out == "vm1\nvm2\n"

    def test_status_is_printed(self, run_cli, api, capsys):
        run_cli("status", "-n", "vm1")
        assert capsys.readouterr().out == "Running\n"

    def test_get_metadata_is_printed(self, run_cli, api, capsys):
        run_cli("get_metadata", "-n", "vm1", "--metadata_name", "k")
        assert capsys.readouterr().out == "some-value\n"

    def test_verbose_enables_debug_logging(self, run_cli, api, monkeypatch):
        levels = []
        monkeypatch.setattr(
            logging,
            "basicConfig",
            lambda **kwargs: levels.append(kwargs.get("level")),
        )
        run_cli("-v", "list")
        assert levels == [logging.DEBUG]

    def test_default_logging_is_warning(self, run_cli, api, monkeypatch):
        levels = []
        monkeypatch.setattr(
            logging,
            "basicConfig",
            lambda **kwargs: levels.append(kwargs.get("level")),
        )
        run_cli("list")
        assert levels == [logging.WARNING]


class TestMainCreate:
    """create forwards a dict built from the parsed namespace."""

    def _create(self, run_cli, api, xml_file, *extra):
        run_cli(
            "create", "-n", "vm1", "--xml", xml_file, "-i", "d.qcow2", *extra
        )
        name, args, _ = api.only
        assert name == "create"
        return args[0]

    def test_xml_file_is_read_into_base_xml(self, run_cli, api, xml_file):
        options = self._create(run_cli, api, xml_file)
        assert options["base_xml"] == (
            "<domain type='kvm'><name>template</name></domain>"
        )

    def test_missing_xml_file_raises(self, run_cli, api):
        with pytest.raises(FileNotFoundError):
            run_cli(
                "create",
                "-n",
                "vm1",
                "--xml",
                "/nonexistent/vm.xml",
                "-i",
                "d.qcow2",
            )
        assert api.calls == []

    def test_name_and_image_are_forwarded(self, run_cli, api, xml_file):
        options = self._create(run_cli, api, xml_file)
        assert options["name"] == "vm1"
        assert options["image"] == "d.qcow2"

    def test_additional_disks_are_forwarded(self, run_cli, api, xml_file):
        options = self._create(
            run_cli,
            api,
            xml_file,
            "--additional-disk",
            "a.qcow2",
            "--additional-disk",
            "b.qcow2",
        )
        assert options["additional_disks"] == ["a.qcow2", "b.qcow2"]

    def test_metadata_is_forwarded_as_a_dict(self, run_cli, api, xml_file):
        options = self._create(
            run_cli, api, xml_file, "--metadata", "role=router"
        )
        assert options["metadata"] == {"role": "router"}

    def test_add_crm_config_cmd_is_renamed(self, run_cli, api, xml_file):
        """main() translates --add-crm-config-cmd to the crm_config_cmd key
        the backend reads."""
        options = self._create(
            run_cli,
            api,
            xml_file,
            "--add-crm-config-cmd",
            "cmd1",
            "--add-crm-config-cmd",
            "cmd2",
        )
        assert options["crm_config_cmd"] == ["cmd1", "cmd2"]

    def test_pinned_host_is_forwarded(self, run_cli, api, xml_file):
        options = self._create(run_cli, api, xml_file, "--pinned-host", "hyp1")
        assert options["pinned_host"] == "hyp1"

    @pytest.mark.xfail(
        strict=True,
        reason="main() guards the assignment with 'if \"enable\" in args', "
        "but 'enable' is never an argparse dest for create, so args.enable "
        "is never set. _configure_vm() treats a missing 'enable' key as "
        "True, so 'create --disable' enables the VM anyway.",
    )
    def test_disable_is_forwarded_as_enable_false(
        self, run_cli, api, xml_file
    ):
        options = self._create(run_cli, api, xml_file, "--disable")
        assert options["enable"] is False

    @pytest.mark.xfail(
        strict=True,
        reason='main() guards the assignment with \'if "live_migration" in '
        "args', but 'live_migration' is never an argparse dest, so the key "
        "is never set and _configure_vm() never writes the _live_migration "
        "metadata. clone and add-to-cluster assign it unconditionally.",
    )
    def test_enable_live_migration_is_renamed(self, run_cli, api, xml_file):
        options = self._create(
            run_cli, api, xml_file, "--enable-live-migration"
        )
        assert options["live_migration"] is True


class TestMainClone:
    def test_xml_is_optional_and_defaults_to_none(self, run_cli, api):
        run_cli("clone", "-n", "vm1", "--dst_name", "vm2")
        name, args, _ = api.only
        assert name == "clone"
        assert args[0]["base_xml"] is None
        assert args[0]["dst_name"] == "vm2"

    def test_xml_file_is_read_when_given(self, run_cli, api, xml_file):
        run_cli("clone", "-n", "vm1", "--dst_name", "vm2", "--xml", xml_file)
        _, args, _ = api.only
        assert args[0]["base_xml"] == (
            "<domain type='kvm'><name>template</name></domain>"
        )

    def test_live_migration_is_renamed(self, run_cli, api):
        run_cli(
            "clone",
            "-n",
            "vm1",
            "--dst_name",
            "vm2",
            "--enable-live-migration",
        )
        _, args, _ = api.only
        assert args[0]["live_migration"] is True

    @pytest.mark.xfail(
        strict=True,
        reason="the clone branch of main() never sets args.enable, and "
        "_configure_vm() treats a missing 'enable' key as True, so "
        "'clone --disable' enables the clone anyway. Same root cause as "
        "TestMainCreate.test_disable_is_forwarded_as_enable_false.",
    )
    def test_disable_is_forwarded_as_enable_false(self, run_cli, api):
        run_cli("clone", "-n", "vm1", "--dst_name", "vm2", "--disable")
        _, args, _ = api.only
        assert args[0]["enable"] is False


class TestMainAddToCluster:
    """add-to-cluster assigns enable and live_migration unconditionally,
    which is what create and clone should be doing too."""

    def test_enable_defaults_to_true(self, run_cli, api):
        run_cli("add-to-cluster", "-n", "vm1")
        name, args, _ = api.only
        assert name == "add_to_cluster"
        assert args[0]["enable"] is True

    def test_disable_is_forwarded_as_enable_false(self, run_cli, api):
        run_cli("add-to-cluster", "-n", "vm1", "--disable")
        _, args, _ = api.only
        assert args[0]["enable"] is False

    def test_live_migration_is_renamed(self, run_cli, api):
        run_cli("add-to-cluster", "-n", "vm1", "--enable-live-migration")
        _, args, _ = api.only
        assert args[0]["live_migration"] is True

    def test_new_name_is_forwarded(self, run_cli, api):
        run_cli("add-to-cluster", "-n", "vm1", "--new-name", "vm2")
        _, args, _ = api.only
        assert args[0]["new_name"] == "vm2"
