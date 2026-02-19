#!/usr/bin/env python3
# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: CC-BY-4.0

"""
Script to test Pacemaker module: start VM
"""

from vm_manager.helpers.pacemaker import Pacemaker

VM_NAME = "vm1"
SLEEP = 1


def main():

    with Pacemaker(VM_NAME) as p:

        state = p.show()
        print(VM_NAME + " state: " + state)
        if state == "Stopped (disabled)":
            print("Start " + VM_NAME)
            p.start()
            p.wait_for("Started")
            print("VM " + VM_NAME + " started")

        else:
            raise Exception("VM is already started")


if __name__ == "__main__":
    main()
