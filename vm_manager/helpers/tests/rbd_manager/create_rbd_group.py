#!/usr/bin/env python3
# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: CC-BY-4.0

"""
Script to test RbdManager module: create group and add / remove an
RBD image from it
"""

from vm_manager.helpers.rbd_manager import RbdManager

CEPH_CONF = "/etc/ceph/ceph.conf"
POOL_NAME = "rbd"

IMG_SIZE = "4M"
IMG_NAME = "img1"
GROUP = "group1"


def main():

    with RbdManager(CEPH_CONF, POOL_NAME) as rbd:

        # Create image
        print("Create image " + IMG_NAME)
        rbd.create_image(IMG_NAME, IMG_SIZE)

        img_list = rbd.list_images()
        print("Image list: " + str(img_list))
        if IMG_NAME not in img_list:
            raise Exception("Could not create image " + IMG_NAME)

        try:
            # Create group
            print("Create group " + GROUP)
            try:
                rbd.create_group(GROUP)
            except Exception as err:
                raise Exception(
                    "Could not create group " + GROUP + ": " + str(err)
                )

            # Verify group has been created
            groups = rbd.list_groups()
            print("Groups: ", str(groups))
            if GROUP not in groups:
                raise Exception("Group is not created")

            # Add image to group
            print("Add " + IMG_NAME + " to group " + GROUP)
            rbd.add_image_to_group(IMG_NAME, GROUP)

            # Verify image is in group
            group_imgs = list(rbd.list_group_images(GROUP))
            print(GROUP + " image list: " + str(group_imgs))
            if IMG_NAME not in group_imgs:
                raise Exception(
                    "Image " + IMG_NAME + " not added to group " + GROUP
                )

            # Remove image from group
            print("Remove " + IMG_NAME + " from group " + GROUP)
            rbd.remove_image_from_group(IMG_NAME, GROUP)

            # Verify image is removed from group
            group_imgs = list(rbd.list_group_images(GROUP))
            print(GROUP + " image list: " + str(group_imgs))
            if IMG_NAME in group_imgs:
                raise Exception(
                    "Image " + IMG_NAME + " not removed from group " + GROUP
                )

            # Remove group
            print("Remove group " + GROUP)
            rbd.remove_group(GROUP)

            # Verify group has been removed
            groups = rbd.list_groups()
            print("Groups: ", str(groups))
            if GROUP in groups:
                raise Exception("Could not remove group " + GROUP)

            # Remove images
            print("Remove image " + IMG_NAME)
            rbd.remove_image(IMG_NAME)

            img_list = rbd.list_images()
            print("Image list: " + str(img_list))
            if IMG_NAME in img_list:
                raise Exception("Could not remove image " + IMG_NAME)

            print("Test finished")

        finally:
            # Cleanup
            if rbd.group_exists(GROUP):
                for img in rbd.list_group_images(GROUP):
                    print("Remove img " + img + " from group")
                    rbd.remove_image_from_group(img, GROUP)
                print("Remove group " + GROUP)
                rbd.remove_group(GROUP)
                print("Group list: " + str(rbd.list_groups()))

            if rbd.image_exists(IMG_NAME):
                print("Remove image " + IMG_NAME)
                rbd.remove_image(IMG_NAME)
                print("Image list: " + str(rbd.list_images()))


if __name__ == "__main__":
    main()
