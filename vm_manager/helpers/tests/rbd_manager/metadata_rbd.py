#!/usr/bin/env python3
# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: CC-BY-4.0

"""
Script to test RbdManager module: write / read metadata on an RBD image
"""

from vm_manager.helpers.rbd_manager import RbdManager

CEPH_CONF = "/etc/ceph/ceph.conf"
POOL_NAME = "rbd"

IMG_SIZE = "4M"
IMG_NAME = "img1"
METADATA = {
    "test1": "metadatatest1",
    "test2": "metadatatest2",
    "test3": "metadatatest3",
    "test4": "metadatatest4",
}


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
            # Set metadata
            print("Set metadata: " + str(METADATA))
            for md in METADATA:
                rbd.set_image_metadata(IMG_NAME, md, METADATA[md])

            # Read metadata
            print(
                "List all metadata from "
                + IMG_NAME
                + ": "
                + str(rbd.list_image_metadata(IMG_NAME))
            )

            for md in METADATA:
                metadata = rbd.get_image_metadata(IMG_NAME, md)
                print("Read metadata " + md + ": " + str(metadata))
                if metadata != METADATA[md]:
                    raise Exception("Could not verify " + md)

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
            if rbd.image_exists(IMG_NAME):
                print("Remove image " + IMG_NAME)
                rbd.remove_image(IMG_NAME)
                print("Image list: " + str(rbd.list_images()))


if __name__ == "__main__":
    main()
