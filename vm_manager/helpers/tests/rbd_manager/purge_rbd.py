#!/usr/bin/env python3
# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: CC-BY-4.0

"""
Script to test RbdManager module: create protected and unprotected
snapshots on an RBD image and purge it
"""

from vm_manager.helpers.rbd_manager import RbdManager

CEPH_CONF = "/etc/ceph/ceph.conf"
POOL_NAME = "rbd"

IMG_SIZE = "4M"
IMG_NAME = "img1"
SNAPS = ["snap0", "snap1", "snap2", "snap3", "snap4", "snap5"]

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
            # Create snapshots
            for snap in SNAPS:
                print("Create snapshot " + snap + " from image " + IMG_NAME)
                rbd.create_snapshot(IMG_NAME, snap)

            # Verify all snaps have been created
            snap_list = rbd.list_snapshots(IMG_NAME)
            print("Snaps from " + IMG_NAME + ": " + str(snap_list))
            for snap in SNAPS:
                if snap not in snap_list:
                    raise Exception("Could not create snapshots " + snap)

            # Protect last three snapshots
            for snap in SNAPS[:3]:
                print("Unprotect " + snap)
                rbd.set_snapshot_protected(IMG_NAME, snap, False)
            for snap in SNAPS[3:]:
                print("Protect " + snap)
                rbd.set_snapshot_protected(IMG_NAME, snap, True)

            # Purge image = remove non-protected snapshots
            print("Purge image: remove non-protected snapshots")
            rbd.purge_image(IMG_NAME)

            # Verify purge
            snap_list = rbd.list_snapshots(IMG_NAME)
            print("Snaps from " + IMG_NAME + ": " + str(snap_list))
            for snap in SNAPS[:3]:
                if snap in snap_list:
                    raise Exception("Error purging " + snap)
            for snap in SNAPS[3:]:
                if snap not in snap_list:
                    raise Exception("Error purging " + snap)

            # Forced purge = remove all snapshosts
            print("Forced purge: remove all snapshots")
            rbd.purge_image(IMG_NAME, force=True)

            snap_list = rbd.list_snapshots(IMG_NAME)
            print("Snaps from " + IMG_NAME + ": " + str(snap_list))

            for snaps in SNAPS:
                if snap in snap_list:
                    raise Exception("Error purging " + snap)

            # Remove image
            print("Remove image " + IMG_NAME)
            rbd.remove_image(IMG_NAME)

            img_list = rbd.list_images()
            print("Image list: " + str(img_list))
            if IMG_NAME in img_list:
                raise Exception("Could not remove image " + IMG_NAME)

            print("Test finished")

        finally:
            # Cleanup
            if rbd.image_exists(IMG_NAME):
                print("Remove image " + IMG_NAME)
                rbd.remove_image(IMG_NAME)  # remove forces purge
                print("Image list: " + str(rbd.list_images()))
