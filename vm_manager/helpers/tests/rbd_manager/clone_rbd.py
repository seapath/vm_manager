#!/usr/bin/env python3
# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: CC-BY-4.0

"""
Script to test RbdManager module: clone RBD image and verify data
"""

from vm_manager.helpers.rbd_manager import RbdManager

CEPH_CONF = "/etc/ceph/ceph.conf"
POOL_NAME = "rbd"

IMG_SIZE = "4M"
IMG1 = "img1"
IMG2 = "img2"
TEXT = "Hello world"

if __name__ == "__main__":

    with RbdManager(CEPH_CONF, POOL_NAME) as rbd:

        # Create image
        print("Create image " + IMG1)
        rbd.create_image(IMG1, IMG_SIZE)

        img_list = rbd.list_images()
        print("Image list: " + str(img_list))
        if IMG1 not in img_list:
            raise Exception("Could not create image " + IMG1)

        try:
            # Write / read image (must use byte array)
            print("Write text to image " + IMG1)
            rbd.write_to_image(IMG1, bytes(TEXT, "utf-8"), 0)

            # Verify
            data = rbd.read_from_image(IMG1, 0, len(TEXT))
            print("Read from image " + IMG1 + ": " + str(data))

            if data.decode() != TEXT:
                raise Exception(
                    "Data read from " + IMG1 + " is not correct: " + str(data)
                )

            # Clone image
            print("Clone image " + IMG1 + " into " + IMG2)
            rbd.clone_image(IMG1, IMG2)

            # Verify
            data = rbd.read_from_image(IMG2, 0, len(TEXT))
            print("Read from image " + IMG2 + ": " + str(data))

            if data.decode() != TEXT:
                raise Exception(
                    "Data read from " + IMG2 + " is not correct: " + str(data)
                )

            # Remove images
            print("Remove images " + IMG1 + " and " + IMG2)
            rbd.remove_image(IMG1)
            rbd.remove_image(IMG2)

            img_list = rbd.list_images()
            print("Image list: " + str(img_list))
            for img in [IMG1, IMG2]:
                if img in img_list:
                    raise Exception("Could not remove image " + img)

            print("Test finished")

        finally:
            # Cleanup
            for img in [IMG1, IMG2]:
                if rbd.image_exists(img):
                    print("Remove image " + img)
                    rbd.remove_image(img)
                    print("Image list: " + str(rbd.list_images()))
