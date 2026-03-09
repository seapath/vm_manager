#!/usr/bin/env python3
# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

from .helpers.libvirt import LibVirtManager
from .exceptions import UuidConflictError
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


def list_all_uuids():
    """
    Return dict mapping UUID strings to VM names for all local VMs.
    """
    with LibVirtManager() as lvm:
        return lvm.list_uuids()


def _create_xml(xml, vm_name):
    """
    Creates a libvirt configuration file according to xml and
    vm_name parameters.
    """
    xml_root = ElementTree.fromstring(xml)
    try:
        xml_root.remove(xml_root.findall("./name")[0])
    except IndexError:
        pass
    existing_uuid = xml_root.findall("./uuid")
    if not existing_uuid or not existing_uuid[0].text:
        try:
            xml_root.remove(existing_uuid[0])
        except IndexError:
            pass
        uuid_element = ElementTree.SubElement(xml_root, "uuid")
        uuid_element.text = str(uuid.uuid4())
    name_element = ElementTree.SubElement(xml_root, "name")
    name_element.text = vm_name

    return ElementTree.tostring(xml_root).decode()


def create(args):
    """
    Create a new VM

    :param vm_name: the VM name
    :param base_xml:  the VM libvirt xml configuration
    """
    xml = _create_xml(args.get("base_xml"), args.get("name"))

    xml_root = ElementTree.fromstring(xml)
    vm_uuid = xml_root.findtext("uuid")
    if vm_uuid:
        existing = list_all_uuids()
        if vm_uuid in existing:
            raise UuidConflictError(
                "UUID {} is already used by VM {}".format(
                    vm_uuid, existing[vm_uuid]
                )
            )

    with LibVirtManager() as lvm:
        lvm.define(xml)
        if args.get("autostart"):
            lvm.set_autostart(args.get("name"), True)

    logger.info("VM " + args.get("name") + " created successfully")


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
    :param autostart: if True, enable autostart on the VM
    """
    with LibVirtManager() as lvm:
        lvm.start(vm_name)

    logger.info("VM " + vm_name + " started")


def autostart(vm_name, enabled):
    """
    Set the autostart flag on a VM

    :param vm_name: the VM name
    :param enabled: True to enable autostart, False to disable
    """
    with LibVirtManager() as lvm:
        lvm.set_autostart(vm_name, enabled)

    state = "enabled" if enabled else "disabled"
    logger.info("VM " + vm_name + " autostart " + state)


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
    :return: the status of the VM, among Starting, Started, Paused, Stopped,
             Stopping, Undefined and FAILED
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
