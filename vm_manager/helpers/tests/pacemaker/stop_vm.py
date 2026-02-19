#!/usr/bin/env python3
# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: CC-BY-4.0

"""
Script to test Pacemaker module: stop VM
"""

from vm_manager.helpers.pacemaker import Pacemaker

VM_NAME = "vm1"
SLEEP = 1


def main():
    with Pacemaker(VM_NAME) as p:

        state = p.show()
        print(VM_NAME + " state: " + state)
        if state == "Started":
            print("Stop " + VM_NAME)
            p.stop()
            p.wait_for("Stopped (disabled)")
            print("VM " + VM_NAME + " stopped")

        else:
            raise Exception("Machine is already stopped")


if __name__ == "__main__":
    main()
