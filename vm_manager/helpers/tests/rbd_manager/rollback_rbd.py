#!/usr/bin/env python3
# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: CC-BY-4.0

"""
Script to test RbdManager module: rollback RBD image to a specific
image snapshot and group snapshot
"""

import time

from vm_manager.helpers.rbd_manager import RbdManager

CEPH_CONF = "/etc/ceph/ceph.conf"
POOL_NAME = "rbd"

IMG_SIZE = "4M"
IMG_NAME = "img1"
SNAP = "snap1"
GROUP = "group1"
TEXT1 = "Hello world"
TEXT2 = "XXXXXXXXXXX"


def write_to_image(rbd, img_name, text):
    """
    Write and read data on an RBD image.
    """
    # Write TEXT to image
    print("Write text '" + text + "' to image " + img_name)
    rbd.write_to_image(img_name, bytes(text, "utf-8"), 0)

    # Verify data read
    data = rbd.read_from_image(img_name, 0, len(text)).decode()
    print("Read from image " + img_name + ": " + data)
    if data != text:
        raise Exception(
            "Data read from " + img_name + " is not correct: " + data
        )


def cleanup(rbd):
    """
    Remove group and image.
    """
    if rbd.group_exists(GROUP):
        print("Remove group " + GROUP)
        rbd.remove_group(GROUP)
        print("Group list: " + str(rbd.list_groups()))

    if rbd.image_exists(IMG_NAME):
        print("Remove image " + IMG_NAME)
        rbd.remove_image(IMG_NAME)  # remove forces purge
        print("Image list: " + str(rbd.list_images()))


if __name__ == "__main__":

    with RbdManager(CEPH_CONF, POOL_NAME) as rbd:

        # Create image
        print("Create image " + IMG_NAME)
        rbd.create_image(IMG_NAME, IMG_SIZE)

        img_list = rbd.list_images()
        print("Image list: " + str(img_list))
        if IMG_NAME not in img_list:
            raise Exception("Could not create image " + IMG_NAME)

        try:
            # Write text on image
            write_to_image(rbd, IMG_NAME, TEXT1)

            # Create image snapshot
            print("Create snapshot " + SNAP + " from image " + IMG_NAME)
            rbd.create_image_snapshot(IMG_NAME, SNAP)

            # Verify snapshot creation
            snap_list = rbd.list_image_snapshots(IMG_NAME)
            print("Snaps from " + IMG_NAME + ": " + str(snap_list))
            if SNAP not in snap_list:
                raise Exception("Could not create snapshot " + SNAP)

            # Check snapshot timestamp
            ts = rbd.get_image_snapshot_timestamp(IMG_NAME, SNAP)
            print("Snapshot " + SNAP + " timestamp: " + str(ts))
            if (
                int(ts.timestamp()) > int(time.time()) + 5
            ):  # Compare with 5 sec delay
                raise Exception(
                    "Incorrect snapshot " + SNAP + " timestamp: " + str(ts)
                )

            # Overwrite data on image
            write_to_image(rbd, IMG_NAME, TEXT2)

            # Rollback to snapshot
            print("Rollback " + IMG_NAME + " to " + SNAP)
            rbd.rollback_image(IMG_NAME, SNAP)

            # Verify data rollback
            data = rbd.read_from_image(IMG_NAME, 0, len(TEXT1)).decode()
            print("Read from image " + IMG_NAME + ": " + data)
            if data != TEXT1:
                raise Exception(
                    "Data read from " + IMG_NAME + " is not correct: " + data
                )

            # Repeat process for group snapshot
            # Create group
            print("Create group " + GROUP)
            rbd.create_group(GROUP)
            groups = rbd.list_groups()
            print("Group list: ", str(groups))
            if GROUP not in groups:
                raise Exception("Could not create group " + GROUP)

            # Add image to group
            print("Add image " + IMG_NAME + " to group " + GROUP)
            rbd.add_image_to_group(IMG_NAME, GROUP)
            print(
                "Group "
                + GROUP
                + " image list: "
                + str(rbd.list_group_images(GROUP))
            )
            if not rbd.is_image_in_group(IMG_NAME, GROUP):
                raise Exception(
                    "Could not add image " + IMG_NAME + " to group " + GROUP
                )

            # Write data to image
            write_to_image(rbd, IMG_NAME, TEXT1)

            # Create group snapshot
            print("Create group snapshot")
            rbd.create_group_snapshot(GROUP, SNAP)
            if SNAP not in rbd.list_group_snapshots(GROUP):
                raise Exception(
                    "Could not create snapshot " + SNAP + " on group " + GROUP
                )

            # Overwrite data on image
            write_to_image(rbd, IMG_NAME, TEXT2)

            # Rollback to snap
            print("Rollback group " + GROUP + " to snap " + SNAP)
            rbd.rollback_group(GROUP, SNAP)

            # Verify data rollback
            data = rbd.read_from_image(IMG_NAME, 0, len(TEXT1)).decode()
            print("Read from image " + IMG_NAME + ": " + data)
            if data != TEXT1:
                raise Exception(
                    "Data read from " + IMG_NAME + " is not correct: " + data
                )

            # Cleanup
            cleanup(rbd)

            if rbd.group_exists(GROUP):
                raise Exception("Could not remove group " + GROUP)

            if rbd.image_exists(IMG_NAME):
                raise Exception("Could not remove image " + IMG_NAME)

            print("Test finished")

        finally:
            cleanup(rbd)
