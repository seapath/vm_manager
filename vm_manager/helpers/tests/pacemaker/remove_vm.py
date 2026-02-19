#!/usr/bin/env python3
# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: CC-BY-4.0

"""
Script to test Pacemaker module: remove VM
NOTE: If the VM is running it will wait until the machine is stopped.
"""

import time

from vm_manager.helpers.pacemaker import Pacemaker

SLEEP = 1
VM_NAME = "vm1"


def main():
    with Pacemaker(VM_NAME) as p:

        print("Resource list: " + str(p.list_resources()))
        try:
            if p.show() != "Stopped":
                print("VM is running, force delete")
                p.delete(True)
            else:
                print("VM is stopped, delete")
                p.delete()

        except Exception as err:
            print("Could not remove VM: " + str(err))

        time.sleep(SLEEP)

        resources = p.list_resources()
        print("Resource list: " + str(resources))
        if VM_NAME in resources:
            raise Exception("Resource " + VM_NAME + " was not removed")


if __name__ == "__main__":
    main()
