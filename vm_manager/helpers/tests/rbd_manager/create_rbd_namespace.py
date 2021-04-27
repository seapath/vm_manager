#!/usr/bin/env python3
# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: CC-BY-4.0

"""
Script to test RbdManager module: verify that RBD images are
accessible only from their namespace
"""

from vm_manager.helpers.rbd_manager import RbdManager

CEPH_CONF = "/etc/ceph/ceph.conf"
POOL_NAME = "rbd"

IMG_SIZE = "4M"
IMG_NAME = "img1"
DEFAULT_NS = "vm"
NS1 = "namespace1"
NS2 = "namespace2"

if __name__ == "__main__":

    with RbdManager(CEPH_CONF, POOL_NAME) as rbd:

        try:
            # Create namespace
            print("Create namespaces " + NS1 + " and " + NS2)
            for ns in [NS1, NS2]:
                try:
                    rbd.create_namespace(ns)
                except Exception as err:
                    print("Could not create namespace " + ns + ": " + str(err))

            ns_list = rbd.list_namespaces()
            print("Namespace list: " + str(ns_list))
            for ns in [NS1, NS2]:
                if ns not in ns_list:
                    raise Exception("Could not create namespace " + ns)

            # Set namespace NS1
            print("Set namespace " + NS1)
            rbd.set_namespace(NS1)

            if rbd.get_namespace() != NS1:
                raise Exception("Could not set namespace " + NS1)

            # Create image
            print("Create image " + IMG_NAME)
            rbd.create_image(IMG_NAME, IMG_SIZE)

            img_list = rbd.list_images()
            print(
                "Image list from namespace "
                + rbd.get_namespace()
                + ": "
                + str(img_list)
            )

            if IMG_NAME not in img_list:
                raise Exception(
                    "Image " + IMG_NAME + " not in namespace " + NS1
                )

            # Switch to NS2
            print("Set namespace " + NS2)
            rbd.set_namespace(NS2)

            img_list = rbd.list_images()
            print(
                "Image list from namespace "
                + rbd.get_namespace()
                + ": "
                + str(img_list)
            )

            if IMG_NAME in img_list:
                raise Exception(
                    "Image " + IMG_NAME + " should not be in namespace " + NS2
                )

            # Back to NS1
            print("Set namespace " + NS1)
            rbd.set_namespace(NS1)

            # Remove images
            print("Remove image " + IMG_NAME)
            rbd.remove_image(IMG_NAME)

            img_list = rbd.list_images()
            print(
                "Image list from namespace "
                + rbd.get_namespace()
                + ": "
                + str(img_list)
            )
            if IMG_NAME in img_list:
                raise Exception(
                    "Could not remove " + IMG_NAME + " from namespace " + NS1
                )

            # Default namespace
            rbd.set_namespace(DEFAULT_NS)

            # Remove namespaces
            print("Remove namespaces " + NS1 + " and " + NS2)
            rbd.remove_namespace(NS1)
            rbd.remove_namespace(NS2)

            ns_list = rbd.list_namespaces()
            print("Namespace list: " + str(ns_list))

            for ns in [NS1, NS2]:
                if ns in img_list:
                    raise Exception("Namespace " + ns + " could not be removed")

            print("Test finished")

        finally:
            # Cleanup
            for ns in [NS1, NS2]:
                if rbd.namespace_exists(ns):
                    rbd.set_namespace(ns)
                    for img in rbd.list_images():
                        rbd.remove_image(img)
                    rbd.set_namespace(DEFAULT_NS)
                    print("Remove namespace " + ns)
                    rbd.remove_namespace(ns)
                    print("Namespace list: " + str(rbd.list_namespaces()))
