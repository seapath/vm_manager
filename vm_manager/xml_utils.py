# Copyright (C) 2026 Savoir-faire Linux Inc.
# SPDX-License-Identifier: Apache-2.0

import uuid
import xml.etree.ElementTree as ElementTree

from .exceptions import UuidConflictError


def prepare_xml_base(xml, vm_name):
    """
    Prepare a libvirt XML configuration by setting the VM name and
    generating a UUID if none is provided.

    :param xml: the base libvirt XML string
    :param vm_name: the VM name to set
    :return: the modified ElementTree root element
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
    return xml_root


def check_uuid_conflict(xml, list_all_uuids_fn):
    """
    Check that the UUID in a libvirt XML does not conflict with
    existing VMs.

    :param xml: the libvirt XML string to check
    :param list_all_uuids_fn: callable returning a dict of
        {uuid_str: vm_name}
    :raises UuidConflictError: if the UUID is already in use
    """
    xml_root = ElementTree.fromstring(xml)
    vm_uuid = xml_root.findtext("uuid")
    if vm_uuid:
        existing = list_all_uuids_fn()
        if vm_uuid in existing:
            raise UuidConflictError(
                "UUID {} is already used by VM {}".format(
                    vm_uuid, existing[vm_uuid]
                )
            )
