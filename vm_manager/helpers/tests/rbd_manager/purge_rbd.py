#!/usr/bin/env python3
# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: CC-BY-4.0

"""
Script to test RbdManager module:
1. Create protected and unprotected snapshots on an RBD image and
purge it.
2. Create different snapshots on a group and purge it.
"""

from vm_manager.helpers.rbd_manager import RbdManager

CEPH_CONF = "/etc/ceph/ceph.conf"
POOL_NAME = "rbd"

IMG_SIZE = "4M"
IMG_NAME = "img1"
SNAPS = ["snap0", "snap1", "snap2", "snap3", "snap4", "snap5"]
GROUP = "group1"

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
            # Create image snapshots
            for snap in SNAPS:
                print("Create snapshot " + snap + " from image " + IMG_NAME)
                rbd.create_image_snapshot(IMG_NAME, snap)

            # Verify all snaps have been created
            print(
                "Snaps from "
                + IMG_NAME
                + ": "
                + str(rbd.list_image_snapshots(IMG_NAME))
            )
            for snap in SNAPS:
                if not rbd.image_snapshot_exists(IMG_NAME, snap):
                    raise Exception(
                        "Could not create snapshot "
                        + snap
                        + " on image "
                        + IMG_NAME
                    )

            # Protect last three snapshots
            for snap in SNAPS[:3]:
                print("Unprotect " + snap)
                rbd.set_image_snapshot_protected(IMG_NAME, snap, False)
            for snap in SNAPS[3:]:
                print("Protect " + snap)
                rbd.set_image_snapshot_protected(IMG_NAME, snap, True)

            # Purge image = remove non-protected snapshots
            print("Purge image: remove non-protected snapshots")
            rbd.purge_image(IMG_NAME)

            # Verify purge
            snap_list = rbd.list_image_snapshots(IMG_NAME)
            print("Snaps from " + IMG_NAME + ": " + str(snap_list))
            for snap in SNAPS[:3]:
                if rbd.image_snapshot_exists(IMG_NAME, snap):
                    raise Exception(
                        "Error purging image "
                        + IMG_NAME
                        + ". Could not remove "
                        + snap
                    )
            for snap in SNAPS[3:]:
                if not rbd.image_snapshot_exists(IMG_NAME, snap):
                    raise Exception(
                        "Error purging image "
                        + IMG_NAME
                        + ". Snapshot "
                        + snap
                        + " has been removed"
                    )

            # Forced purge = remove all snapshosts
            print("Forced purge: remove all snapshots")
            rbd.purge_image(IMG_NAME, force=True)

            snap_list = rbd.list_image_snapshots(IMG_NAME)
            print("Snaps from image " + IMG_NAME + ": " + str(snap_list))
            if len(snap_list) != 0:
                raise Exception("Error purging image " + IMG_NAME)

            # Remove image
            print("Remove image " + IMG_NAME)
            rbd.remove_image(IMG_NAME)

            img_list = rbd.list_images()
            print("Image list: " + str(img_list))
            if IMG_NAME in img_list:
                raise Exception("Could not remove image " + IMG_NAME)

            # Create group
            print("Create group " + GROUP)
            rbd.create_group(GROUP)
            groups = rbd.list_groups()
            print("Group list: ", str(groups))
            if GROUP not in groups:
                raise Exception("Could not create group " + GROUP)

            # Create snapshots on group
            print("Create group snapshots")
            for snap in SNAPS:
                rbd.create_group_snapshot(GROUP, snap)

            print(
                "Group snapshot list: " + str(rbd.list_group_snapshots(GROUP))
            )
            for snap in SNAPS:
                if not rbd.group_snapshot_exists(GROUP, snap):
                    raise Exception(
                        "Could not create snapshot "
                        + snap
                        + " on group "
                        + GROUP
                    )

            # Remove snapshots from group
            print("Purge group " + GROUP)
            rbd.purge_group(GROUP)

            # Verify purge
            snap_list = rbd.list_group_snapshots(GROUP)
            print("Snaps from group " + GROUP + ": " + str(snap_list))
            if len(snap_list) != 0:
                raise Exception("Error purging group" + GROUP)

            # Remove group
            print("Remove group " + IMG_NAME)
            rbd.remove_group(GROUP)

            group_list = rbd.list_groups()
            print("Group list: " + str(group_list))
            if GROUP in group_list:
                raise Exception("Could not remove group " + GROUP)

            print("Test finished")

        finally:
            # Cleanup
            if rbd.group_exists(GROUP):
                print("Remove group " + GROUP)
                rbd.remove_group(GROUP)
                print("Group list: " + str(rbd.list_groups()))

            if rbd.image_exists(IMG_NAME):
                print("Remove image " + IMG_NAME)
                rbd.remove_image(IMG_NAME)  # remove forces purge
                print("Image list: " + str(rbd.list_images()))
