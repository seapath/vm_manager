#!/usr/bin/env python3
# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: CC-BY-4.0

"""
Script to test RbdManager module: rollback RBD image to a specific snapshot
"""

from vm_manager.helpers.rbd_manager import RbdManager

CEPH_CONF = "/etc/ceph/ceph.conf"
POOL_NAME = "rbd"

IMG_SIZE = "4M"
IMG_NAME = "img1"
SNAP = "snap1"
TEXT1 = "Hello world"
TEXT2 = "XXXXXXXXXXX"

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
            # Write TEXT to image
            print("Write text '" + TEXT1 + "' to image " + IMG_NAME)
            rbd.write_to_image(IMG_NAME, bytes(TEXT1, "utf-8"), 0)

            # Verify data read
            data = rbd.read_from_image(IMG_NAME, 0, len(TEXT1)).decode()
            print("Read from image " + IMG_NAME + ": " + data)
            if data != TEXT1:
                raise Exception(
                    "Data read from " + IMG_NAME + " is not correct: " + data
                )

            # Create snapshot
            print("Create snapshot " + SNAP + " from image " + IMG_NAME)
            rbd.create_snapshot(IMG_NAME, SNAP)

            # Verify snapshot creation
            snap_list = rbd.list_snapshots(IMG_NAME)
            print("Snaps from " + IMG_NAME + ": " + str(snap_list))
            if SNAP not in snap_list:
                raise Exception("Could not create snapshot " + SNAP)

            # Overwrite data on image
            print("Write text '" + TEXT2 + "' to image " + IMG_NAME)
            rbd.write_to_image(IMG_NAME, bytes(TEXT2, "utf-8"), 0)

            # Verify data read
            data = rbd.read_from_image(IMG_NAME, 0, len(TEXT2)).decode()
            print("Read from image " + IMG_NAME + ": " + data)
            if data != TEXT2:
                raise Exception(
                    "Data read from " + IMG_NAME + " is not correct: " + data
                )

            # Rollback to snapshot
            print("Rollback " + IMG_NAME + " to " + SNAP)
            rbd.rollback_image_to_snap(IMG_NAME, SNAP)

            # Verify data rollback
            data = rbd.read_from_image(IMG_NAME, 0, len(TEXT1)).decode()
            print("Read from image " + IMG_NAME + ": " + data)
            if data != TEXT1:
                raise Exception(
                    "Data read from " + IMG_NAME + " is not correct: " + data
                )

            # Remove image
            print("Remove image " + IMG_NAME)
            rbd.remove_image(IMG_NAME)

            img_list = rbd.list_images()
            print("Image list: " + str(img_list))
            if IMG_NAME in img_list:
                raise Exception("Could not remove image " + IMG_NAME)

        finally:
            # Cleanup
            if rbd.image_exists(IMG_NAME):
                print("Remove image " + IMG_NAME)
                rbd.remove_image(IMG_NAME)  # remove forces purge
                print("Image list: " + str(rbd.list_images()))
