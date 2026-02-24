# Copyright (C) 2026, Sprecher Automation
# SPDX-License-Identifier: Apache-2.0

"""
Argparse-only tests for the vm_manager_cmd CLI.

These tests exercise the argparse layer in isolation and have no
cluster dependencies. The end-to-end test that drives main() through
the real backend lives in test_vm_manager_cmd_cluster.py (which CI
ignores because it needs Ceph/Pacemaker).
"""

import pytest

import vm_manager
from vm_manager.vm_manager_cmd import get_parser

pytestmark = pytest.mark.skipif(
    not vm_manager.cluster_mode,
    reason="--additional-disk is only registered in cluster mode",
)


BASE_CREATE_ARGS = [
    "create",
    "--name",
    "vm1",
    "--xml",
    "/nonexistent/vm.xml",
    "-i",
    "/nonexistent/sys.qcow2",
]


class TestCreateAdditionalDiskFlag:
    def test_single_additional_disk_parses_to_list(self):
        parser = get_parser()
        args = parser.parse_args(
            BASE_CREATE_ARGS + ["--additional-disk", "/nonexistent/a.qcow2"]
        )
        assert args.additional_disks == ["/nonexistent/a.qcow2"]

    def test_multiple_additional_disks_accumulate_in_order(self):
        parser = get_parser()
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

    def test_omitted_flag_defaults_to_none(self):
        parser = get_parser()
        args = parser.parse_args(BASE_CREATE_ARGS)
        assert args.additional_disks is None

    def test_additional_disk_singular_attr_not_used(self):
        """Guard against accidentally dropping dest= — without it,
        argparse would derive args.additional_disk (singular) and the
        backend would never see the list.
        """
        parser = get_parser()
        args = parser.parse_args(
            BASE_CREATE_ARGS + ["--additional-disk", "/nonexistent/a.qcow2"]
        )
        assert not hasattr(args, "additional_disk")
