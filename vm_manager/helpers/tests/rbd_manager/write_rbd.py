#!/usr/bin/env python3
# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: CC-BY-4.0

"""
Script to test RbdManager module: create RBD image, test write / read
functions and remove RBD image
"""

from vm_manager.helpers.rbd_manager import RbdManager

CEPH_CONF = "/etc/ceph/ceph.conf"
POOL_NAME = "rbd"

IMG_SIZE = "4M"
IMG_NAME = "img1"
TEXT = "Hello world"

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
            # Write to image (must use byte array)
            print("Write text '" + TEXT + "' to image " + IMG_NAME)
            rbd.write_to_image(IMG_NAME, bytes(TEXT, "utf-8"), 0)

            # Verify data read
            data = rbd.read_from_image(IMG_NAME, 0, len(TEXT)).decode()
            print("Read from image " + IMG_NAME + ": " + data)
            if data != TEXT:
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

            print("Test finished")

        finally:
            # Cleanup
            if rbd.image_exists(IMG_NAME):
                print("Remove image " + IMG_NAME)
                rbd.remove_image(IMG_NAME)
                print("Image list: " + str(rbd.list_images()))

if __name__ == "__main__":
    main()
