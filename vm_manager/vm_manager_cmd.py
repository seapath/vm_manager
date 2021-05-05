#!/usr/bin/env python3
# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""
A cli wrapper for vm_manager module
"""

import argparse
import vm_manager
import logging

if __name__ == "__main__":
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
    subparsers.add_parser("stop", help="Stop a VM")
    subparsers.add_parser("disable", help="Disable a VM")
    subparsers.add_parser("enable", help="Enable a VM")
    subparsers.add_parser("list", help="List all VMs")
    for name, subparser in subparsers.choices.items():
        if name != "list":
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
    create_parser.add_argument(
        "-i", "--image", type=str, required=True, help="VM image disk to import"
    )
    create_parser.add_argument(
        "--disable",
        action="store_true",
        required=False,
        help="Do not enable the VM after its creation",
    )
    create_parser.add_argument(
        "--force",
        action="store_true",
        required=False,
        help="Force the VM creation and overwrites existing VM with the same "
        "name",
    )
    args = parser.parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
        logging.debug("Enable debug traces")
    else:
        logging.basicConfig(level=logging.WARNING)
    if args.command == "list":
        vm_manager.list_vms()
    elif args.command == "start":
        vm_manager.start(args.name)
    elif args.command == "stop":
        vm_manager.stop(args.name)
    elif args.command == "remove":
        vm_manager.remove(args.name)
    elif args.command == "create":
        with open(args.xml, "r") as xml:
            xml_data = xml.read()
        vm_manager.create(
            args.name,
            xml_data,
            args.image,
            enable=(not args.disable),
            force=args.force,
        )
    elif args.command == "disable":
        vm_manager.disable_vm(args.name)
    elif args.command == "enable":
        vm_manager.enable_vm(args.name)
