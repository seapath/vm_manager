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


def get_parser():
    """Return the argument parser for vm_manager_cmd."""
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
    console_parser = subparsers.add_parser(
        "console", help="Connect to a VM console"
    )

    if not vm_manager.cluster_mode:
        create_parser.add_argument(
            "--no-autostart",
            action="store_true",
            required=False,
            help="Do not enable autostart on the VM",
        )
        autostart_parser = subparsers.add_parser(
            "autostart", help="Set the autostart flag on a VM"
        )
        autostart_group = autostart_parser.add_mutually_exclusive_group(
            required=True
        )
        autostart_group.add_argument(
            "--enable",
            action="store_true",
            default=False,
            help="Enable autostart",
        )
        autostart_group.add_argument(
            "--disable",
            action="store_true",
            default=False,
            help="Disable autostart",
        )

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
        import_parser = subparsers.add_parser(
            "add-to-cluster",
            help="Add an existing libvirt VM to the cluster",
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
        "--xml",
        type=str,
        required=False,
        default=None,
        help="VM libvirt XML path (optional if generation options are"
        " used)",
    )
    create_parser.add_argument(
        "--vcpus", type=int, default=1, help="Number of vCPUs"
    )
    create_parser.add_argument(
        "--memory",
        type=int,
        default=2048,
        help="RAM in MiB (default 2048)",
    )
    create_parser.add_argument(
        "--cpuset",
        type=str,
        default=None,
        help="Comma-separated host CPU list for pinning, " 'e.g. "2,3,4,5"',
    )
    create_parser.add_argument(
        "--description",
        type=str,
        default=None,
        help="VM description",
    )
    create_parser.add_argument(
        "--rt",
        action="store_true",
        default=False,
        help="Enable real-time (FIFO scheduling, PMU off, "
        "host-passthrough)",
    )
    create_parser.add_argument(
        "--rt-priority",
        type=int,
        default=1,
        help="RT FIFO priority (default 1)",
    )
    create_parser.add_argument(
        "--emulatorpin",
        type=str,
        default=None,
        help="Emulator thread CPU pinning",
    )
    create_parser.add_argument(
        "--hugepages",
        action="store_true",
        default=False,
        help="Enable 1GiB hugepages memory with NUMA",
    )
    create_parser.add_argument(
        "--balloon",
        action="store_true",
        default=False,
        help="Enable virtio memballoon",
    )
    create_parser.add_argument(
        "--vnc",
        action="store_true",
        default=False,
        help="Enable VNC graphics",
    )
    create_parser.add_argument(
        "--vnc-listen",
        type=str,
        default="127.0.0.1",
        help="VNC listen address (default 127.0.0.1)",
    )
    create_parser.add_argument(
        "--secure-boot",
        action="store_true",
        default=False,
        help="Enable UEFI secure boot",
    )
    create_parser.add_argument(
        "--net",
        type=str,
        action="append",
        default=None,
        help="Network interface (repeatable). Format: "
        "type=bridge,source=br0,mac=xx:xx:xx:xx:xx:xx[,vlan=N]",
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

        create_parser.add_argument(
            "--additional-disk",
            type=str,
            metavar="PATH",
            dest="additional_disks",
            action="append",
            required=False,
            default=None,
            help="Path to an additional qcow2 disk image to import into Ceph "
            "and attach to the VM. Can be specified multiple times. The "
            "disks are attached as vdb, vdc, ... and share the --disk-bus "
            "setting with the system disk.",
        )

        for p in [create_parser, clone_parser, import_parser]:
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

        import_parser.add_argument(
            "-i",
            "--image",
            type=str,
            required=False,
            default=None,
            help="VM image disk to import into Ceph (default: use the disk"
            " from the libvirt VM definition)",
        )
        import_parser.add_argument(
            "-p",
            "--progress",
            action="store_true",
            required=False,
            help="Print disk import progress bar",
        )
        import_parser.add_argument(
            "--disk-bus",
            type=str,
            required=False,
            default="virtio",
            help="Set the image disk bus type (default virtio)",
        )
        import_parser.add_argument(
            "--new-name",
            type=str,
            required=False,
            default=None,
            help="New VM name (if omitted, keeps the original libvirt VM "
            "name)",
        )
        import_parser.add_argument(
            "--nostart",
            action="store_true",
            required=False,
            help="Do not start the VM after import",
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
            default="libvirtadmin",
            help="SSH user to connect to the VM",
        )

    # if cluster_mode end

    return parser


def main():
    parser = get_parser()
    args = parser.parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
        logging.debug("Enable debug traces")
    else:
        logging.basicConfig(level=logging.WARNING)
    if args.command == "list":
        print("\n".join(vm_manager.list_vms()))
    elif args.command == "start":
        if vm_manager.cluster_mode:
            vm_manager.start(args.name)
        else:
            vm_manager.start(args.name, autostart=not args.no_autostart)
    elif args.command == "stop":
        vm_manager.stop(args.name, force=args.force)
    elif args.command == "remove":
        vm_manager.remove(args.name)
    elif args.command == "create":
        if args.xml:
            with open(args.xml, "r") as xml:
                args.base_xml = xml.read()
        else:
            from vm_manager.xml_generator import generate_xml

            gen_opts = vars(args).copy()
            if gen_opts.get("cpuset"):
                gen_opts["cpuset"] = [
                    int(c) for c in gen_opts["cpuset"].split(",")
                ]
            # argparse already maps --secure-boot → secure_boot,
            # --rt-priority → rt_priority, --vnc-listen → vnc_listen
            args.base_xml = generate_xml(gen_opts)
        if "live_migration" in args:
            args.live_migration = args.enable_live_migration
        if "add_crm_config_cmd" in args:
            args.crm_config_cmd = args.add_crm_config_cmd
        if "disable" in args and args.disable:
            if "enable" in args:
                args.enable = not args.disable
        else:
            if "enable" in args:
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
    elif args.command == "add-to-cluster":
        args.live_migration = args.enable_live_migration
        args.crm_config_cmd = args.add_crm_config_cmd
        if "disable" in args and args.disable:
            args.enable = not args.disable
        else:
            args.enable = True
        vm_manager.add_to_cluster(vars(args))
    elif args.command == "autostart":
        vm_manager.autostart(args.name, args.enable)
    elif args.command == "console":
        if vm_manager.cluster_mode:
            vm_manager.console(args.name, args.ssh_user)
        else:
            vm_manager.console(args.name)


if __name__ == "__main__":
    main()
