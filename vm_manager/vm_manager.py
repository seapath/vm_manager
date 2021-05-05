# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

import os
import logging
import uuid
import re
from errno import ENOENT
import xml.etree.ElementTree as ET

from vm_manager.helpers.rbd_manager import RbdManager
from vm_manager.helpers.pacemaker import Pacemaker
from vm_manager.helpers.libvirt import LibVirtManager

XML_PACEMAKER_PATH = "/etc/pacemaker"

CEPH_CONF = "/etc/ceph/ceph.conf"
POOL_NAME = "rbd"
NAMESPACE = ""

logger = logging.getLogger(__name__)

"""
A module to manage VMs in Seapath cluster.
"""


def list_vms():
    """
    List all the VM
    :return: the VM list
    """
    return Pacemaker.list_resources()


def create(
    vm_name, xml, system_image, data_size=None, force=False, enable=False
):
    """
    Create a new VM
    :param vm_name: the VM name
    :param xml: the VM libvirt xml configuration
    :param system_image: the path of the system image disk to use
    :param data_size: the optional image data disk size. Used suffix K, M, or G
    :param force: set to True to replace a existing VM with this new VM
    :param enable: set to True to enable the VM in Pacemaker
    """

    # Check vm_name
    if not (
        vm_name
        and isinstance(vm_name, str)
        and bool(re.match("^[a-zA-Z0-9]*$", vm_name))
    ):
        raise ValueError(
            "'vm_name' parameter must be a non-empty string without spaces and"
            " special chars"
        )

    logger.info("Create VM: " + vm_name + " from " + system_image)

    # Check required files exist
    for f in [CEPH_CONF, system_image]:
        if not os.path.isfile(f):
            raise IOError(ENOENT, "Could not find file", f)

    # Set name and uuid in xml
    xml_root = ET.fromstring(xml)
    try:
        xml_root.remove(xml_root.findall("./name")[0])
        xml_root.remove(xml_root.findall("./uuid")[0])
    except IndexError:
        pass
    name_element = ET.SubElement(xml_root, "name")
    name_element.text = vm_name
    name_element = ET.SubElement(xml_root, "uuid")
    name_element.text = str(uuid.uuid4())
    rbd_secret = None
    with LibVirtManager() as libvirt_manager:
        libvirt_secrets = libvirt_manager.get_virsh_secrets()
        for secret, secret_value in libvirt_secrets.items():
            if secret == "client.libvirt secret":
                rbd_secret = secret_value
    if not rbd_secret:
        raise Exception("Can't found rbd secret")
    disk_name = "system_" + vm_name
    disk_xml = ET.fromstring(
        """<disk type="network" device="disk">
            <driver name="qemu" type="raw" cache="writeback" />
            <auth username="libvirt">
                <secret type="ceph" uuid="{}" />
            </auth>
            <source protocol="rbd" name="{}/{}">
                <host name="rbd" port="6789" />
            </source>
            <target dev="vda" bus="virtio" />
        </disk>""".format(
            rbd_secret, POOL_NAME, disk_name
        )
    )
    xml_root.find("devices").append(disk_xml)
    xml = ET.tostring(xml_root).decode()

    with RbdManager(CEPH_CONF, POOL_NAME, NAMESPACE) as rbd:

        # Check if VM already exists and overwrite it if force is enabled
        if rbd.group_exists(vm_name):
            if force:
                remove(vm_name)
            else:
                raise Exception("VM " + vm_name + " already exists")

        # Group creation
        rbd.create_group(vm_name)
        if not rbd.group_exists(vm_name):
            raise Exception("Could not create group " + vm_name)

        disk_name = "system_" + vm_name
        if rbd.image_exists(disk_name):
            rbd.remove_image(disk_name)

        logger.info("Image list :" + str(rbd.list_images()))

        # Import qcow2 disk
        logger.info("Import qcow2 disk")
        rbd.import_qcow2(system_image, disk_name)

        if not rbd.image_exists(disk_name):
            raise Exception("Could not import qcow2: " + system_image)

        # Add image to group
        logger.info("Add " + disk_name + " to group " + vm_name)
        rbd.add_image_to_group(disk_name, vm_name)

        # Write metadata
        logger.info("Set metadata")
        rbd.set_metadata(disk_name, "vm_name", vm_name)
        rbd.set_metadata(disk_name, "xml", xml)

    logger.info("VM image " + disk_name + " created")

    # Define and export configuration
    xml_path = os.path.join(XML_PACEMAKER_PATH, vm_name + ".xml")
    with LibVirtManager() as lvm:
        logger.info("Define xml")
        lvm.define(xml)
        lvm.undefine(vm_name)

    # Check libvirt xml configuration is correct
    if not os.path.isfile(xml_path):
        raise IOError(ENOENT, "Could not find file", xml_path)

    if enable:
        # Add VM to cluster
        with Pacemaker(vm_name) as p:

            p.add_vm(xml_path)
            if vm_name not in p.list_resources():
                raise Exception("Resource " + vm_name + " was not added")
            p.wait_for("Started")

        logger.info("VM " + vm_name + " added to cluster")


def remove(vm_name):
    """
    Remove a VM from cluster
    :param vm_name: the VM name to be removed
    """

    # Check if VM exists
    with RbdManager(CEPH_CONF, POOL_NAME, NAMESPACE) as rbd:
        if not rbd.group_exists(vm_name):
            raise Exception("VM " + vm_name + " does not exist")

    with Pacemaker(vm_name) as p:

        if vm_name in p.list_resources():
            if p.show() != "Stopped":
                print("VM is running, force delete")
                p.delete(True)
            else:
                print("VM is stopped, delete")
                p.delete()

            if vm_name in p.list_resources():
                raise Exception("Could not remove VM " + vm_name)

    with RbdManager(CEPH_CONF, POOL_NAME, NAMESPACE) as rbd:

        disk_name = "system_" + vm_name
        rbd.remove_group(vm_name)
        if rbd.image_exists(disk_name):
            rbd.remove_image(disk_name)
        else:
            logger.info(disk_name + " image does not exist")

        if rbd.group_exists(vm_name):
            raise Exception("Could not remove group " + vm_name)

        if rbd.image_exists(disk_name):
            raise Exception("Could not remove image " + disk_name)

    logger.info("VM " + vm_name + " removed")


def enable(vm_name):
    """
    Enable a VM in Pacemaker
    :param vm_name: the VM name to be enabled
    """


def disable(vm_name):
    """
    Stop and disable a VM in Pacemaker without removing it
    :param vm_name: the VM name to be disabled
    """


def start(vm_name):
    """
    Start or resume an stopped or paused VM
    The VM must enabled before being started
    :param vm_name: the VM to be started
    """

    with Pacemaker(vm_name) as p:

        if vm_name in p.list_resources():
            state = p.show()
            if state != "Started":
                print("Start " + vm_name)
                p.start()
                p.wait_for("Started")
                print("VM " + vm_name + " started")
            else:
                print("VM " + vm_name + " is already started")
        else:
            raise Exception("VM " + vm_name + " is not on the cluster")


def is_enabled(vm_name):
    """
    Ask if the VM is enabled in Pacemaker
    :param vm_name: the vm_name to be checked
    :return: True if the VM is enabled, False otherwise
    """


def status(vm_name):
    """
    Get the VM status
    :param vm_name: the VM in which the status must be checked
    :return: the status of the VM, among starting, started, pause, stopped and
             disabled
    """


def stop(vm_name):
    """
    Stop a VM
    :param vm_name: the VM to be stopped
    """

    with Pacemaker(vm_name) as p:

        if vm_name in p.list_resources():
            state = p.show()
            if state != "Stopped":
                print("Stop " + vm_name)
                p.stop()
                p.wait_for("Stopped")
                print("VM " + vm_name + " stopped")
            else:
                print("VM " + vm_name + " is already stopped")
        else:
            raise Exception("VM " + vm_name + " is not on the cluster")


def pause(vm_name):
    """
    Pause a VM
    :param vm_name: the VM to be paused
    """


def clone(new_vm_name, src_vm, data="clone", force=False, enable=False):
    """
    Create a new VM from another
    :param new_vm_name: the New VM name
    :param src_vm: the source VM to be cloned
    :param data: the data disk. Can be "clone" to copy the source data disk,
                 None to disable data disk or a integer size with suffix K, M,
                 G to create a new empty data disk of the given size
    :param force: set to True to replace an existing VM with this new VM
    :param enable: set to True to enable the VM in Pacemaker
    """


def snapshot_create(vm_name, snapshot_name, snapshot_type="OS"):
    """
    Create a snapshot. The snapshot can be a system disk snapshot only or
    a VM snapshot (os disk and data disk)
    :param vm_name: the VM to be snapshot
    :param snapshot_name: the snapshot name
    :parameter snapshot_type: the snapshot type to perform: "OS" for a system
                              snapshot or "VM" for VM snapshot
    """


def snapshot_remove(vm_name, snapshot_name, snapshot_type="OS"):
    """
    Remove a snapshot
    :param vm_name: the VM in which the snapshot must be removed
    :param snapshot_name: the name of the snapshot to be removed
    :param snapshot_type: the snapshot type: "OS" for a system snapshot or
                          "VM" for VM snapshot
    """


def snapshots_list(vm_name, snapshot_type="OS"):
    """
    Get the snapshots list of a VM
    :param vm_name: the VM name from which to list the snapshots
    :param snapshot_type: the snapshot type to list: "OS" for a system snapshot
                          or "VM" for VM snapshot
    :return: the snapshot list
    """


def snapshot_purge(vm_name, snapshot_type="OS"):
    """
    Remove all snapshots of the given type on the given VM
    :param vm_name: the VM name to be purged
    :param snapshot_type: the snapshot type to purge: "OS" for a system snapshot
                          or "VM" for VM snapshot
    """


def snapshot_rollback(vm_name, snapshot_name, snapshot_type="OS"):
    """
    Restore a VM to a previous state based on the given snapshot
    :param vm_name: the VM name to be restored
    :param snapshot_name: the snapshot name to be used for rollback
    :param snapshot_type: the snapshot type used for the rollback: "OS" for a
                          system snapshot or "VM" for VM snapshot. A VM
                          rollback will rollback the system and the data
    """


def list_metadata(vm_name):
    """
    List all metadata associated to the given VM
    :param vm_name: the VM name from which the metadata will be listed
    :return: the metadata list
    """


def get_metadata(vm_name, metadata_name):
    """
    Get a metadata value
    :param vm_name: the VM name where the metadata is stored
    :param metadata_name: the metadata name to get
    :return: the metadata value (a str)
    """


def set_metadata(vm_name, metadata_name, metadata_value):
    """
    Set a metadata with the given value. Create it if the metadata does not
    exist yet
    :param vm_name: the VM name where the metadata will be stored
    :param metadata_name: the metadata name to be set
    :param metadata_value: the metadata value to set
    """
