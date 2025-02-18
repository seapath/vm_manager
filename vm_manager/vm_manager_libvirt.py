#!/usr/bin/env python3
# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

from .helpers.libvirt import LibVirtManager
import xml.etree.ElementTree as ElementTree
import uuid
import logging

logger = logging.getLogger(__name__)

OS_DISK_PREFIX = "system_"


def list_vms():
    """
    Return a list of the VMs.
    :return: the VM list
    """
    with LibVirtManager() as lvm:
        return lvm.list()


def _create_xml(xml, vm_name):
    """
    Creates a libvirt configuration file according to xml and
    vm_name parameters.
    """
    xml_root = ElementTree.fromstring(xml)
    try:
        xml_root.remove(xml_root.findall("./name")[0])
        xml_root.remove(xml_root.findall("./uuid")[0])
    except IndexError:
        pass
    name_element = ElementTree.SubElement(xml_root, "name")
    name_element.text = vm_name
    name_element = ElementTree.SubElement(xml_root, "uuid")
    name_element.text = str(uuid.uuid4())

    return ElementTree.tostring(xml_root).decode()


def create(vm_name, base_xml, *args, **kwargs):
    """
    Create a new VM
    :param vm_name: the VM name
    :param base_xml:  the VM libvirt xml configuration
    """

    xml = _create_xml(base_xml, vm_name)

    with LibVirtManager() as lvm:
        lvm.define(xml)

    logger.info("VM " + vm_name + " created successfully")


def remove(vm_name):
    """
    Remove a VM
    :param vm_name: the VM name to be removed
    """
    with LibVirtManager() as lvm:
        if vm_name not in lvm.list():
            logger.info(vm_name + "does not exist")
        elif lvm._conn.lookupByName(vm_name).isActive():
            lvm.force_stop(vm_name)
        lvm.undefine(vm_name)

    logger.info("VM " + vm_name + " removed")


def start(vm_name):
    """
    Start or resume a stopped or paused VM
    The VM must enabled before being started
    :param vm_name: the VM to be started
    """
    with LibVirtManager() as lvm:
        lvm.start(vm_name)

    logger.info("VM " + vm_name + " started")


def stop(vm_name, force=False):
    """
    Stop a VM
    :param vm_name: the VM to be stopped
    :param force: Set to True to force stop (virtually unplug the VM)
    """
    with LibVirtManager() as lvm:
        if force:
            lvm.force_stop(vm_name)
            logger.info("Forced VM " + vm_name + " stop")
        else:
            lvm.stop(vm_name)
            logger.info("VM " + vm_name + " stopped")


def status(vm_name):
    """
    Get the VM status
    :param vm_name: the VM for which the status must be checked
    :return:    the status of the VM, among Starting, Started, Paused,
                Stopped, Stopping, Undefined and FAILED
    """
    with LibVirtManager() as lvm:
        return lvm.status(vm_name)

def console(vm_name):
    """
    Open a virsh console for the given VM
    :param vm_name: the VM name to open the console
    """
    with LibVirtManager() as lvm:
        lvm.console(vm_name)
