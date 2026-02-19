#!/usr/bin/env python3
# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""
A simple cli wrapper for libvirt_helper module
"""

import argparse
from vm_manager.helpers.libvirt import LibVirtManager


def main():
    parser = argparse.ArgumentParser(description="libvirt helper cli wrapper")
    subparsers = parser.add_subparsers(
        help="command", dest="command", required=True, metavar="command"
    )
    subparsers.add_parser("list", help="list all VMs")
    subparsers.add_parser("secrets", help="list all libvirt secrets")
    export_parser = subparsers.add_parser(
        "export", help="export a VM configuration"
    )
    define_parser = subparsers.add_parser(
        "define", help="validate and create a VM from an XML configuration"
    )
    export_parser.add_argument(
        "domain", type=str, help="VM domain name to export"
    )
    export_parser.add_argument(
        "destination",
        type=str,
        help="full path where the configuration is exported",
    )
    define_parser.add_argument("xml", type=str, help="The XML file path")
    args = parser.parse_args()
    if args.command == "list":
        with LibVirtManager() as libvirt_manager:
            for vm in libvirt_manager.list():
                print(vm)
    elif args.command == "secrets":
        with LibVirtManager() as libvirt_manager:
            for name, value in libvirt_manager.get_virsh_secrets().items():
                print("{}: {}".format(name, value))
    elif args.command == "define":
        with open(args.xml, "r") as f:
            xml = f.read()
        with LibVirtManager() as libvirt_manager:
            libvirt_manager.define(xml)
    elif args.command == "export":
        LibVirtManager.export_configuration(args.domain, args.destination)


if __name__ == "__main__":
    main()
