#!/usr/bin/env python3
# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: CC-BY-4.0

"""
Script to test Pacemaker module: import a qcow2 image and add VM to
cluster
"""

from vm_manager.helpers.pacemaker import Pacemaker

VM_NAME = "vm1"
VM_XML = "/usr/share/testdata/vm.xml"

START_TIMEOUT = 120
STOP_TIMEOUT = 30
MONITOR_TIMEOUT = 60
MONITOR_INTERVAL = 10
MIGRATE_FROM_TIMEOUT = 60
MIGRATE_TO_TIMEOUT = 120


if __name__ == "__main__":

    with Pacemaker(VM_NAME) as p:

        print("Resource list: " + str(p.list_resources()))
        print("Add VM to cluster")
        try:
            p.add_vm(
                VM_XML,
                START_TIMEOUT,
                STOP_TIMEOUT,
                MONITOR_TIMEOUT,
                MONITOR_INTERVAL,
                MIGRATE_FROM_TIMEOUT,
                MIGRATE_TO_TIMEOUT,
                seapath_managed=False,
            )
        except Exception as err:
            raise Exception(
                "Could not add VM " + VM_NAME + " to Pacemaker: " + str(err)
            )

        resources = p.list_resources()
        print("Resource list: " + str(resources))
        if VM_NAME not in resources:
            raise Exception("Resource " + VM_NAME + " was not added")

        p.wait_for("Started")
