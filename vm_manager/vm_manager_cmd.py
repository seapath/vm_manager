#!/usr/bin/env python3
# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""
A cli wrapper for vm_manager module
"""

import argparse
import vm_manager
import logging
import datetime


class ParseMetaData(argparse.Action):
    """
    Class to parse metadata argument.
    """

    def __call__(self, parser, namespace, values, option_string=None):
        d = getattr(namespace, self.dest, {})
        if not d:
            d = {}

        if values:
            for item in values:
                key, value = item.split("=", 1)
                d[key] = value

        setattr(namespace, self.dest, d)


def main():
    parser = argparse.ArgumentParser(description="vm_manager cli wrapper")
    parser.add_argument(
        "-v",
        "--verbose",
        help="increase output verbosity",
        action="store_true",
        required=False,
    )
    subparsers = parser.add_subparsers(
        help="command", dest="command", required=True, metavar="command"
    )
    create_parser = subparsers.add_parser("create", help="Create a new VM")
    subparsers.add_parser("remove", help="Remove a VM")
    subparsers.add_parser("start", help="Start a VM")
    stop_parser = subparsers.add_parser("stop", help="Stop a VM")
    subparsers.add_parser("list", help="List all VMs")
    subparsers.add_parser("status", help="Print VM status")
    console_parser = subparsers.add_parser("console", help="Connect to a VM console")


    if vm_manager.cluster_mode:
        clone_parser = subparsers.add_parser("clone", help="Clone a VM")
        enable_parser = subparsers.add_parser("enable", help="Enable a VM")
        subparsers.add_parser("disable", help="Disable a VM")
        create_snap_parser = subparsers.add_parser(
            "create_snapshot", help="Create a VM snapshot"
        )
        remove_snap_parser = subparsers.add_parser(
            "remove_snapshot", help="Remove a snapshot from a VM"
        )
        list_snaps_parser = subparsers.add_parser(
            "list_snapshots", help="List all snapshots from a VM"
        )
        purge_parser = subparsers.add_parser(
            "purge", help="Purge snapshots from a VM"
        )
        rollback_parser = subparsers.add_parser(
            "rollback", help="Rollback a VM to a given snapshot"
        )
        list_md_parser = subparsers.add_parser(
            "list_metadata", help="Lists all metadata from an image"
        )
        set_md_parser = subparsers.add_parser(
            "set_metadata", help="Set metadata value"
        )
        get_md_parser = subparsers.add_parser(
            "get_metadata", help="Get metadata value"
        )
        add_colocation_parser = subparsers.add_parser(
            "add_colocation", help="Add a colocation constraint"
        )
        add_pacemaker_remote_parser = subparsers.add_parser(
            "add_pacemaker_remote",
            help="Add a pacemaker-remote resource for the VM",
        )
        remove_pacemaker_remote_parser = subparsers.add_parser(
            "remove_pacemaker_remote",
            help="Remove a pacemaker-remote resource for the VM",
        )

    for name, subparser in subparsers.choices.items():
        if name not in ("list", "console"):
            subparser.add_argument(
                "-n",
                "--name",
                type=str,
                required=True,
                help="The VM name",
            )
    create_parser.add_argument(
        "--xml", type=str, required=True, help="VM libvirt XML path"
    )
    stop_parser.add_argument(
        "-f",
        "--force",
        required=False,
        action="store_true",
        help="Force VM stop (virtual unplug) - not implemented yet for cluster"
        " mode",
    )
    console_parser.add_argument(
        "name",
        type=str,
        help="The VM name",
    )

    if vm_manager.cluster_mode:

        clone_parser.add_argument(
            "--nostart",
            action="store_true",
            required=False,
            help="No start after enable",
        )

        enable_parser.add_argument(
            "--nostart",
            action="store_true",
            required=False,
            help="No start after enable",
        )

        create_parser.add_argument(
            "--nostart",
            action="store_true",
            required=False,
            help="No start after enable",
        )

        create_parser.add_argument(
            "-i",
            "--image",
            type=str,
            required=True,
            help="VM image disk to import",
        )

        create_parser.add_argument(
            "-p",
            "--progress",
            action="store_true",
            required=False,
            help="Print disk import progress bar",
        )

        create_parser.add_argument(
            "--disk-bus",
            type=str,
            required=False,
            default="virtio",
            help="Set the image disk bus type in the VM, "
            "must be a valid type recognized by libvirt (default virtio)",
        )

        for p in [create_parser, clone_parser]:
            p.add_argument(
                "--disable",
                action="store_true",
                default=None,
                required=False,
                help="Do not enable the VM after its creation",
            )
            p.add_argument(
                "--force",
                action="store_true",
                default=None,
                required=False,
                help="Force the VM creation and overwrites existing VM with "
                "the same name",
            )
            p.add_argument(
                "--metadata",
                type=str,
                metavar="key=value",
                required=False,
                help="Set a number of key-value metadata pairs"
                "(do not put spaces before or after the = sign)",
                nargs="+",
                action=ParseMetaData,
            )
            p.add_argument(
                "--pinned-host",
                type=str,
                required=False,
                default=None,
                help="Pin the VM on the given host",
            )
            p.add_argument(
                "--preferred-host",
                type=str,
                required=False,
                default=None,
                help="Deploy the VM on the given host in priority",
            )
            p.add_argument(
                "--enable-live-migration",
                action="store_true",
                required=False,
                help="Enables live migration for the VM",
            )
            p.add_argument(
                "--migration-user",
                type=str,
                required=False,
                default=None,
                help="Sets the user used for live migration",
            )
            p.add_argument(
                "--stop-timeout",
                type=str,
                required=False,
                default=None,
                help="Sets the timeout in seconds for stopping a guest "
                "(default 30)",
            )
            p.add_argument(
                "--migrate-to-timeout",
                type=str,
                required=False,
                default=None,
                help="Sets the timeout in seconds for live migration "
                "(default 120)",
            )
            p.add_argument(
                "--migration-downtime",
                type=str,
                required=False,
                default=None,
                help="Sets the allowed downtime for live migration in ms "
                "(default 0)",
            )
            p.add_argument(
                "--add-crm-config-cmd",
                action="append",
                required=False,
                default=None,
                help="Sets a crm configure command to run when enabling this "
                "guest",
            )
            p.add_argument(
                "--priority",
                required=False,
                default=None,
                help="Sets a priority for this guest",
            )
            p.add_argument(
                "--pacemaker-meta",
                type=str,
                metavar="key=value",
                required=False,
                help='Set a key-value pacemaker "meta".'
                 " Can be used multiple times. "
                "(do not put spaces before or after the = sign)",
                nargs="+",
                action=ParseMetaData,
            )
            p.add_argument(
                "--pacemaker-params",
                type=str,
                metavar="key=value",
                required=False,
                help='Set a key-value pacemaker "params".'
                 " Can be used multiple times. "
                "(do not put spaces before or after the = sign)",
                nargs="+",
                action=ParseMetaData,
            )
            p.add_argument(
                "--pacemaker-utilization",
                type=str,
                metavar="key=value",
                required=False,
                help='Set a key-value pacemaker "utilization".'
                 " Can be used multiple times. "
                "(do not put spaces before or after the = sign)",
                nargs="+",
                action=ParseMetaData,
            )

        clone_parser.add_argument(
            "--dst_name", type=str, required=True, help="Destination VM name"
        )

        clone_parser.add_argument(
            "--clear_constraint",
            action="store_true",
            required=False,
            help="Do not keep location constraint",
        )

        clone_parser.add_argument(
            "--clear-pacemaker-meta",
            action="store_true",
            required=False,
            help="Do not keep custom pacemaker meta",
        )

        clone_parser.add_argument(
            "--clear-pacemaker-params",
            action="store_true",
            required=False,
            help="Do not keep custom pacemaker params",
        )

        clone_parser.add_argument(
            "--clear-pacemaker-utilization",
            action="store_true",
            required=False,
            help="Do not keep custom pacemaker utilization",
        )

        clone_parser.add_argument(
            "--xml", type=str, required=False, help="VM libvirt XML path"
        )

        create_snap_parser.add_argument(
            "--snap_name",
            type=str,
            required=True,
            help="Snapshot to be created",
        )

        remove_snap_parser.add_argument(
            "--snap_name",
            type=str,
            required=True,
            help="Snapshot to be removed",
        )

        purge_parser.add_argument(
            "--date",
            type=lambda s: datetime.datetime.strptime(s, "%d/%m/%Y %H:%M:%S"),
            required=False,
            help="Date until snapshots must be removed, i.e., 20/04/2021 "
            "14:02:32",
        )

        purge_parser.add_argument(
            "--number",
            type=int,
            required=False,
            help="Number of snapshots to delete starting from the oldest",
        )

        rollback_parser.add_argument(
            "--snap_name",
            type=str,
            required=True,
            help="Snapshot to be rollbacked",
        )

        get_md_parser.add_argument(
            "--metadata_name",
            type=str,
            required=True,
            help="Metadata name to be read",
        )

        set_md_parser.add_argument(
            "--metadata_name",
            type=str,
            required=True,
            help="Metadata name to be stored",
        )

        set_md_parser.add_argument(
            "--metadata_value",
            type=str,
            required=True,
            help="Metadata value to be stored",
        )

        add_colocation_parser.add_argument(
            "resources",
            type=str,
            nargs="+",
            help="VMs or other Pacemaker resources to be colocated with the "
            "VM",
        )

        add_colocation_parser.add_argument(
            "--strong",
            action="store_true",
            required=False,
            help="Create a strong colocation constraint",
        )

        add_pacemaker_remote_parser.add_argument(
            "--remote_name",
            type=str,
            required=True,
            help="Pacemaker remote resource name",
        )
        add_pacemaker_remote_parser.add_argument(
            "--remote_address",
            type=str,
            required=True,
            help="Pacemaker remote resource address or hostname",
        )
        add_pacemaker_remote_parser.add_argument(
            "--remote_port",
            type=str,
            required=False,
            help="Pacemaker remote resource port",
        )
        add_pacemaker_remote_parser.add_argument(
            "--remote_timeout",
            type=str,
            required=False,
            help="Pacemaker remote resource start timeout",
        )
        console_parser.add_argument(
            "--ssh-user",
            type=str,
            required=False,
            default="admin",
            help="SSH user to connect to the VM",
        )

    # if cluster_mode end

    args = parser.parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
        logging.debug("Enable debug traces")
    else:
        logging.basicConfig(level=logging.WARNING)
    if args.command == "list":
        print("\n".join(vm_manager.list_vms()))
    elif args.command == "start":
        vm_manager.start(args.name)
    elif args.command == "stop":
        vm_manager.stop(args.name, force=args.force)
    elif args.command == "remove":
        vm_manager.remove(args.name)
    elif args.command == "create":
        with open(args.xml, "r") as xml:
            args.base_xml = xml.read()
        args.live_migration = args.enable_live_migration
        args.crm_config_cmd = args.add_crm_config_cmd
        if args.disable:
            args.enable = not args.disable
        else:
            args.enable = True
        vm_manager.create(vars(args))
    elif args.command == "clone":
        args.base_xml = None
        if args.xml:
            with open(args.xml, "r") as xml:
                args.base_xml = xml.read()
        args.live_migration = args.enable_live_migration
        args.crm_config_cmd = args.add_crm_config_cmd
        vm_manager.clone(vars(args))
    elif args.command == "disable":
        vm_manager.disable_vm(args.name)
    elif args.command == "enable":
        vm_manager.enable_vm(args.name, args.nostart)
    elif args.command == "status":
        print(vm_manager.status(args.name))
    elif args.command == "create_snapshot":
        vm_manager.create_snapshot(args.name, args.snap_name)
    elif args.command == "remove_snapshot":
        vm_manager.remove_snapshot(args.name, args.snap_name)
    elif args.command == "list_snapshots":
        print(vm_manager.list_snapshots(args.name))
    elif args.command == "purge":
        vm_manager.purge_image(args.name, args.date, args.number)
    elif args.command == "rollback":
        vm_manager.rollback_snapshot(args.name, args.snap_name)
    elif args.command == "list_metadata":
        print(vm_manager.list_metadata(args.name))
    elif args.command == "get_metadata":
        print(vm_manager.get_metadata(args.name, args.metadata_name))
    elif args.command == "set_metadata":
        vm_manager.set_metadata(
            args.name, args.metadata_name, args.metadata_value
        )
    elif args.command == "add_colocation":
        vm_manager.add_colocation(
            args.name, *args.resources, strong=args.strong
        )
    elif args.command == "remove_pacemaker_remote":
        vm_manager.remove_pacemaker_remote(args.name)
    elif args.command == "add_pacemaker_remote":
        vm_manager.add_pacemaker_remote(
            args.name,
            args.remote_name,
            args.remote_address,
            remote_node_port=args.remote_port,
            remote_node_timeout=args.remote_timeout,
        )
    elif args.command == "console":
        if vm_manager.cluster_mode:
            vm_manager.console(args.name, args.ssh_user)
        else:
            vm_manager.console(args.name)

if __name__ == "__main__":
    main()
