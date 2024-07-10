# Copyright (C) 2021, RTE (http://www.rte-france.com)
# Copyright (C) 2024 Savoir-faire Linux Inc.
# SPDX-License-Identifier: Apache-2.0

import os
import logging
import uuid
import re
import datetime
from errno import ENOENT
import xml.etree.ElementTree as ElementTree
import configparser

from .helpers.rbd_manager import RbdManager
from .helpers.pacemaker import Pacemaker
from .helpers.libvirt import LibVirtManager

XML_PACEMAKER_PATH = "/etc/pacemaker"

CEPH_CONF = "/etc/ceph/ceph.conf"
POOL_NAME = "rbd"
NAMESPACE = ""

RESERVED_NAMES = ["xml"]
OS_DISK_PREFIX = "system_"

logger = logging.getLogger(__name__)

"""
A module to manage VMs in Seapath cluster.
"""


def _check_name(name):
    """
    Raise ValueError if name is an empty string, contains special
    characters or is inside the RESERVED_NAMES list.
    """
    if name in RESERVED_NAMES:
        raise ValueError("Parameter " + name + " is a reserved word")
    if (
        not name
        or not isinstance(name, str)
        or not bool(re.match("^[a-zA-Z0-9]*$", name))
    ):
        raise ValueError("Parameter must not contain spaces or special chars")


def _create_vm_group(vm_name, force=False):
    """
    Create vm_name group and check its creation. Group can be
    overwritten if force is set to True.
    """
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

    logger.info("VM group " + vm_name + " created successfully")


def _create_xml(xml, vm_name):
    """
    Creates a libvirt configuration file according to xml and
    disk_name parameters.
    """
    disk_name = OS_DISK_PREFIX + vm_name
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
    rbd_secret = None
    with LibVirtManager() as libvirt_manager:
        libvirt_secrets = libvirt_manager.get_virsh_secrets()
        for secret, secret_value in libvirt_secrets.items():
            if secret == "client.libvirt secret":
                rbd_secret = secret_value
    if not rbd_secret:
        raise Exception("Can't found rbd secret")
    disk_xml = ElementTree.fromstring(
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
    return ElementTree.tostring(xml_root).decode()


def _configure_vm(vm_options):
    """
    Configure VM vm_name: set initial metadata, define libvirt xml
    configuration and add it on Pacemaker if enable is set to True.
    """

    xml = _create_xml(vm_options["base_xml"], vm_options["name"])

    # Add to group and set initial metadata
    with RbdManager(CEPH_CONF, POOL_NAME, NAMESPACE) as rbd:
        disk_name = OS_DISK_PREFIX + vm_options["name"]
        rbd.add_image_to_group(disk_name, vm_options["name"])
        logger.info(
            "Image " + disk_name + " added to group " + vm_options["name"]
        )

        rbd.set_image_metadata(disk_name, "vm_name", vm_options["name"])
        rbd.set_image_metadata(disk_name, "xml", xml)
        rbd.set_image_metadata(disk_name, "_base_xml", vm_options["base_xml"])
        if "live_migration" in vm_options:
            rbd.set_image_metadata(disk_name, "_live_migration", "true")
        if "migration_user" in vm_options:
            rbd.set_image_metadata(
                disk_name, "_migration_user", vm_options["migration_user"]
            )
        if "stop_timeout" in vm_options:
            rbd.set_image_metadata(
                disk_name, "_stop_timeout", vm_options["stop_timeout"]
            )
        if "migrate_to_timeout" in vm_options:
            rbd.set_image_metadata(
                disk_name,
                "_migrate_to_timeout",
                vm_options["migrate_to_timeout"],
            )
        if "migration_downtime" in vm_options:
            rbd.set_image_metadata(
                disk_name,
                "_migration_downtime",
                vm_options["migration_downtime"],
            )
        if "pinned_host" in vm_options:
            rbd.set_image_metadata(
                disk_name, "_pinned_host", vm_options["pinned_host"]
            )
        elif "preferred_host" in vm_options:
            rbd.set_image_metadata(
                disk_name, "_preferred_host", vm_options["preferred_host"]
            )
        if "crm_config_cmd" in vm_options:
            vm_options["crm_config_cmd_multiline"] = """{}""".format(
                "\n".join(vm_options["crm_config_cmd"])
            )
            rbd.set_image_metadata(
                disk_name,
                "_crm_config_cmd",
                vm_options["crm_config_cmd_multiline"],
            )
        if "priority" in vm_options:
            rbd.set_image_metadata(
                disk_name, "_priority", vm_options["priority"]
            )
        if "metadata" in vm_options:
            for name, data in vm_options["metadata"].items():
                rbd.set_image_metadata(disk_name, name, data)
    logger.info("Image " + disk_name + " initial metadata set")

    # Define libvirt xml configuration
    with LibVirtManager() as lvm:
        lvm.define(xml)
        lvm.undefine(vm_options["name"])
    logger.info("libvirt xml config defined for VM " + vm_options["name"])

    # Enable on Pacemaker
    if "enable" not in vm_options or (
        "enable" in vm_options and vm_options["enable"]
    ):
        enable_vm(vm_options["name"])


def _get_observer_host():
    """
    Get the observer host stored in /etc/cluster.conf
    """
    parser = configparser.ConfigParser()
    with open("/etc/cluster.conf", "r") as fd:
        parser.read_file(fd)
    if "observer" in parser["machines"]:
        return parser["machines"]["observer"]
    else:
        return None


def list_vms(enabled=False):
    """
    Return a list of the VMs.
    :param enabled: if True only list enabled VMs, otherwise list all of them
    :return: the VM list
    """
    if enabled:
        return Pacemaker.list_resources()
    else:
        with RbdManager(CEPH_CONF, POOL_NAME, NAMESPACE) as rbd:
            return rbd.list_groups()


def create(vm_options_with_nones):
    """
    Create a new VM
    The VM will never switch to another host
    """
    # Validate parameters and required files
    vm_options = {
        k: v for k, v in vm_options_with_nones.items() if v is not None
    }
    _check_name(vm_options["name"])

    if "metadata" in vm_options:
        if not isinstance(vm_options["metadata"], dict):
            raise ValueError("metadata parameter must be a dictionary")

        for name, value in vm_options["metadata"].items():
            _check_name(name)

    for f in [CEPH_CONF, vm_options["image"]]:
        if not os.path.isfile(f):
            raise IOError(ENOENT, "Could not find file", f)

    if "pinned_host" in vm_options and not Pacemaker.is_valid_host(
        vm_options["pinned_host"]
    ):
        pinned_host = vm_options["pinned_host"]
        raise Exception(f"{pinned_host} is not valid hypervisor")
    if "preferred_host" in vm_options and not Pacemaker.is_valid_host(
        vm_options["preferred_host"]
    ):
        preferred_host = vm_options["preferred_host"]
        raise Exception(f"{preferred_host} is not a valid hypervisor")

    # Create VM group
    if "force" not in vm_options:
        vm_options["force"] = False
    _create_vm_group(vm_options["name"], vm_options["force"])

    with RbdManager(CEPH_CONF, POOL_NAME, NAMESPACE) as rbd:

        try:
            # Overwrite image if necessary
            disk_name = OS_DISK_PREFIX + vm_options["name"]
            if rbd.image_exists(disk_name):
                rbd.remove_image(disk_name)

            # Import qcow2 disk
            logger.info("Import qcow2 disk")
            rbd.import_qcow2(vm_options["image"], disk_name)
            if not rbd.image_exists(disk_name):
                raise Exception(
                    "Could not import qcow2: " + vm_options["image"]
                )

            # Configure VM
            vm_options["disk_name"] = disk_name
            _configure_vm(vm_options)

        except Exception as err:
            remove(vm_options["name"])
            raise err

    logger.info("VM " + vm_options["name"] + " created successfully")


def remove(vm_name):
    """
    Remove a VM from cluster
    :param vm_name: the VM name to be removed
    """

    # Disable from Pacemaker
    disable_vm(vm_name)

    # Undefine configuration from libvirt
    with LibVirtManager() as lvm:
        if vm_name in lvm.list():
            lvm.undefine(vm_name)

    # Remove group and image from RBD cluster
    with RbdManager(CEPH_CONF, POOL_NAME, NAMESPACE) as rbd:

        disk_name = OS_DISK_PREFIX + vm_name
        if rbd.group_exists(vm_name):
            rbd.remove_group(vm_name)

        if rbd.image_exists(disk_name):
            rbd.remove_image(disk_name)

        if rbd.group_exists(vm_name):
            raise Exception("Could not remove group " + vm_name)

        if rbd.image_exists(disk_name):
            raise Exception("Could not remove image " + disk_name)

    logger.info("VM " + vm_name + " removed")


def enable_vm(vm_name):
    """
    Enable a VM in Pacemaker
    :param vm_name: the VM name to be enabled
    """

    with Pacemaker(vm_name) as p:

        if vm_name not in p.list_resources():
            xml_path = os.path.join(XML_PACEMAKER_PATH, vm_name + ".xml")
            disk_name = OS_DISK_PREFIX + vm_name
            preferred_host = None
            pinned_host = None
            crm_config_cmd = None
            priority = "0"
            live_migration = "false"
            migration_user = "root"
            stop_timeout = "30"
            migrate_to_timeout = "120"
            migration_downtime = "0"
            remote_node = None
            remote_node_address = None
            remote_node_port = None
            remote_node_timeout = None

            with RbdManager(CEPH_CONF, POOL_NAME, NAMESPACE) as rbd:
                try:
                    preferred_host = rbd.get_image_metadata(
                        disk_name, "_preferred_host"
                    )
                except KeyError:
                    pass
                try:
                    pinned_host = rbd.get_image_metadata(
                        disk_name, "_pinned_host"
                    )
                except KeyError:
                    pass
                try:
                    live_migration_str = rbd.get_image_metadata(
                        disk_name, "_live_migration"
                    )
                    if live_migration_str == "true":
                        live_migration = "true"
                except KeyError:
                    pass
                try:
                    migration_user = rbd.get_image_metadata(
                        disk_name, "_migration_user"
                    )
                except KeyError:
                    pass
                try:
                    stop_timeout = rbd.get_image_metadata(
                        disk_name, "_stop_timeout"
                    )
                except KeyError:
                    pass
                try:
                    migrate_to_timeout = rbd.get_image_metadata(
                        disk_name, "_migrate_to_timeout"
                    )
                except KeyError:
                    pass
                try:
                    migration_downtime = rbd.get_image_metadata(
                        disk_name, "_migration_downtime"
                    )
                except KeyError:
                    pass
                try:
                    crm_config_cmd_multi = rbd.get_image_metadata(
                        disk_name, "_crm_config_cmd"
                    )
                    crm_config_cmd = crm_config_cmd_multi.split("\n")
                except KeyError:
                    pass
                try:
                    priority = rbd.get_image_metadata(disk_name, "_priority")
                except KeyError:
                    pass
                try:
                    remote_node = rbd.get_image_metadata(
                        disk_name, "_remote_node"
                    )
                except KeyError:
                    pass
                try:
                    remote_node_address = rbd.get_image_metadata(
                        disk_name, "_remote_node_address"
                    )
                except KeyError:
                    pass
                try:
                    remote_node_port = rbd.get_image_metadata(
                        disk_name, "_remote_node_port"
                    )
                except KeyError:
                    pass
                try:
                    remote_node_timeout = rbd.get_image_metadata(
                        disk_name, "_remote_node_timeout"
                    )
                except KeyError:
                    pass

            if pinned_host and not Pacemaker.is_valid_host(pinned_host):
                raise Exception(f"{pinned_host} is not valid hypervisor")
            if preferred_host and not Pacemaker.is_valid_host(preferred_host):
                raise Exception(f"{preferred_host} is not valid hypervisor")
            vm_options = {
                "xml": xml_path,
                "start_timeout": "120",
                "stop_timeout": stop_timeout,
                "monitor_timeout": "60",
                "monitor_interval": "10",
                "migrate_from_timeout": "60",
                "migrate_to_timeout": migrate_to_timeout,
                "migration_downtime": migration_downtime,
                "is_managed": False,
                "force_stop": False,
                "seapath_managed": True,
                "live_migration": live_migration,
                "migration_user": migration_user,
                "priority": priority,
                "pacemaker_remote": remote_node,
                "pacemaker_remote_addr": remote_node_address,
                "pacemaker_remote_port": remote_node_port,
                "pacemaker_remote_timeout": remote_node_timeout,
            }
            p.add_vm(vm_options)

            if vm_name not in p.list_resources():
                raise Exception(
                    "Could not add VM " + vm_name + " to the cluster"
                )
            observer = _get_observer_host()
            if observer:
                p.disable_location(observer)
            if pinned_host:
                p.pin_location(pinned_host)
            elif preferred_host:
                p.default_location(preferred_host)
            if crm_config_cmd:
                for cmd in crm_config_cmd:
                    p.run_crm_cmd(cmd)
            p.manage()
            p.wait_for("Started")

        else:
            logger.warning("VM " + vm_name + " is already on the cluster")

    logger.info("VM " + vm_name + " enabled on the cluster")


def disable_vm(vm_name):
    """
    Stop and disable a VM in Pacemaker without removing it
    :param vm_name: the VM name to be disabled
    """
    with Pacemaker(vm_name) as p:

        if vm_name in p.list_resources():
            if p.show().split(" ")[0] == "FAILED":
                logger.info(
                    "VM "
                    + vm_name
                    + " is in FAILED state, clean and force delete"
                )
                p.delete(force=True, clean=True)
            elif p.show().split(" ")[0] != "Stopped":
                logger.info("VM " + vm_name + " is running, force delete")
                p.delete(force=True, clean=False)
            else:
                logger.info("VM " + vm_name + " is stopped, delete")
                p.delete(force=False, clean=False)

            if vm_name in p.list_resources():
                raise Exception(
                    "Could not remove VM " + vm_name + " from the cluster"
                )

        else:
            logger.warning("VM " + vm_name + " is not on the cluster")

    logger.info("VM " + vm_name + " disabled from the cluster")


def start(vm_name):
    """
    Start or resume a stopped or paused VM
    The VM must enabled before being started
    :param vm_name: the VM to be started
    """

    with Pacemaker(vm_name) as p:

        if vm_name in p.list_resources():
            state = p.show()
            if state != "Started":
                logger.info("Start " + vm_name)
                p.start()
                p.wait_for("Started")
                logger.info("VM " + vm_name + " started")
            else:
                logger.info("VM " + vm_name + " is already started")
        else:
            raise Exception("VM " + vm_name + " is not on the cluster")


def is_enabled(vm_name):
    """
    Ask if the VM is enabled in Pacemaker
    :param vm_name: the vm_name to be checked
    :return: True if the VM is enabled, False otherwise
    """
    return vm_name in Pacemaker.list_resources()


def status(vm_name):
    """
    Get the VM status
    :param vm_name: the VM for which the status must be checked
    :return: the status of the VM, among Starting, Started, Paused,
             Stopped, Stopping, Disabled, Undefined and FAILED
    """
    with RbdManager(CEPH_CONF, POOL_NAME, NAMESPACE) as rbd:
        if not rbd.group_exists(vm_name):
            return "Undefined"

    with Pacemaker(vm_name) as p:
        if vm_name in p.list_resources():
            return p.show()
        else:
            return "Disabled"


def stop(vm_name, force=False):
    """
    Stop a VM
    :param vm_name: the VM to be stopped
    """
    with Pacemaker(vm_name) as p:

        if vm_name in p.list_resources():
            state = p.show()
            if state != "Stopped (disabled)":
                logger.info("Stop " + vm_name)
                if force:
                    logger.info(
                        "The option --force isn't implemented yet for cluster "
                        "mode"
                    )
                p.stop()
                p.wait_for("Stopped (disabled)")
                logger.info("VM " + vm_name + " stopped")
            else:
                logger.info("VM " + vm_name + " is already stopped")
        else:
            raise Exception("VM " + vm_name + " is not on the cluster")


def clone(vm_options_with_nones):
    """
    Create a new VM from another
    """
    vm_options = {
        k: v for k, v in vm_options_with_nones.items() if v is not None
    }
    src_vm_name = vm_options["name"]
    dst_vm_name = vm_options["dst_name"]
    if src_vm_name == dst_vm_name:
        raise ValueError(
            "Source and destination images cannot have the same name "
            + src_vm_name
        )

    _check_name(dst_vm_name)

    if "metadata" in vm_options:
        if not isinstance(vm_options["metadata"], dict):
            raise ValueError("metadata parameter must be a dictionary")

        for name, value in vm_options["metadata"].items():
            _check_name(name)

    src_disk = OS_DISK_PREFIX + src_vm_name
    dst_disk = OS_DISK_PREFIX + dst_vm_name

    if "base_xml" not in vm_options:
        with RbdManager(CEPH_CONF, POOL_NAME, NAMESPACE) as rbd:
            vm_options["base_xml"] = rbd.get_image_metadata(
                src_disk, "_base_xml"
            )
        if "base_xml" not in vm_options:
            raise Exception("Could not find xml libvirt configuration")
    if (
        "clear_constraint" not in vm_options
        and "preferred_host" not in vm_options
        and "pinned_host" not in vm_options
    ):
        with RbdManager(CEPH_CONF, POOL_NAME, NAMESPACE) as rbd:
            try:
                vm_options["preferred_host"] = rbd.get_image_metadata(
                    src_disk, "_preferred_host"
                )
            except KeyError:
                pass
            try:
                vm_options["pinned_host"] = rbd.get_image_metadata(
                    src_disk, "_pinned_host"
                )
            except KeyError:
                pass
    if vm_options.pinned_host and not Pacemaker.is_valid_host(
        vm_options.pinned_host
    ):
        raise Exception(f"{vm_options.pinned_host} is not valid hypervisor")
    elif vm_options.preferred_host and not Pacemaker.is_valid_host(
        vm_options.preferred_host
    ):
        raise Exception(f"{vm_options.preferred_host} is not valid hypervisor")
    if "force" not in vm_options:
        vm_options["force"] = False
    _create_vm_group(dst_vm_name, vm_options["force"])

    with RbdManager(CEPH_CONF, POOL_NAME, NAMESPACE) as rbd:
        try:
            # Overwrite image if necessary
            if rbd.image_exists(dst_disk):
                rbd.remove_image(dst_disk)

            # Note: Only deep-copy works for images that are on a group
            # (destination img will keep the snaps but not the group)
            rbd.copy_image(
                src_disk, dst_disk, overwrite=vm_options["force"], deep=True
            )
            if not rbd.image_exists(dst_disk):
                raise Exception("Could not create image disk " + dst_disk)
            try:
                rbd.remove_image_metadata(dst_disk, "_preferred_host")
            except KeyError:
                pass
            try:
                rbd.remove_image_metadata(dst_disk, "_pinned_host")
            except KeyError:
                pass

            # Configure VM
            vm_options["name"] = dst_vm_name
            _configure_vm(vm_options)

        except Exception as err:
            remove(dst_vm_name)
            if not rbd.is_image_in_group(src_disk, src_vm_name):
                rbd.add_image_to_group(src_disk, src_vm_name)
            raise err

    logger.info(
        "VM " + src_vm_name + " successfully cloned into " + dst_vm_name
    )


def create_snapshot(vm_name, snapshot_name):
    """
    Create a snapshot. The snapshot can be a system disk snapshot only or
    a VM snapshot (os disk and data disk).
    :param vm_name: the VM to be snapshot
    :param snapshot_name: the snapshot name
    """

    _check_name(snapshot_name)

    with RbdManager(CEPH_CONF, POOL_NAME, NAMESPACE) as rbd:

        disk_name = OS_DISK_PREFIX + vm_name
        if rbd.image_snapshot_exists(disk_name, snapshot_name):
            raise Exception(
                "Snapshot "
                + snapshot_name
                + " already exists on image "
                + disk_name
            )
        rbd.create_image_snapshot(disk_name, snapshot_name)
        logger.info(
            "Snapshot "
            + snapshot_name
            + " from image "
            + disk_name
            + " successfully created"
        )


def remove_snapshot(vm_name, snapshot_name):
    """
    Remove a snapshot
    :param vm_name: the VM from which the snapshot must be removed
    :param snapshot_name: the name of the snapshot to be removed
    """
    with RbdManager(CEPH_CONF, POOL_NAME, NAMESPACE) as rbd:
        disk_name = OS_DISK_PREFIX + vm_name
        rbd.remove_image_snapshot(disk_name, snapshot_name)
        logger.info(
            "Snapshot "
            + snapshot_name
            + " from image "
            + disk_name
            + " successfully removed"
        )


def list_snapshots(vm_name):
    """
    Get the snapshot list of a VM.
    :param vm_name: the VM name from which to list the snapshots
    :return: the snapshot list
    """
    with RbdManager(CEPH_CONF, POOL_NAME, NAMESPACE) as rbd:
        disk_name = OS_DISK_PREFIX + vm_name
        return rbd.list_image_snapshots(disk_name)


def purge_image(vm_name, date=None, number=None):
    """
    Remove all snapshots of the given type on the given VM.
    :param vm_name: the VM name to be purged
    :param date: date until snapshots must be removed
    :param number: number of snapshots to delete starting from the oldest
    """

    if date:
        if number:
            raise ValueError("Only date or number arguments must be provided")

        if not isinstance(date, datetime.datetime):
            raise ValueError("Parameter date is not datetime")

        disk_name = OS_DISK_PREFIX + vm_name
        with RbdManager(CEPH_CONF, POOL_NAME, NAMESPACE) as rbd:

            # snapshot list is sorted by creation date
            for snap in rbd.list_image_snapshots(disk_name, flat=False):
                snap_ts = rbd.get_image_snapshot_timestamp(
                    disk_name, snap["id"]
                )
                if snap_ts.timestamp() < date.timestamp():
                    rbd.remove_image_snapshot(disk_name, snap["name"])

            logger.info(
                "Snapshots of image "
                + disk_name
                + " previous to "
                + str(date)
                + " have been removed"
            )

    elif number:
        if not isinstance(number, int) or number < 1:
            raise ValueError("Parameter number must be a positive integer")

        disk_name = OS_DISK_PREFIX + vm_name
        with RbdManager(CEPH_CONF, POOL_NAME, NAMESPACE) as rbd:

            # snapshot list is sorted by creation date
            snap_list = rbd.list_image_snapshots(disk_name)
            if len(snap_list) <= number:
                rbd.purge_image(disk_name)
                logger.info(
                    "All snapshots from image "
                    + disk_name
                    + " successfully removed"
                )
            else:
                for snap in snap_list[:number]:
                    rbd.remove_image_snapshot(disk_name, snap)
                logger.info(
                    "First "
                    + str(number)
                    + " snapshots of image "
                    + disk_name
                    + " have been removed"
                )
    else:

        with RbdManager(CEPH_CONF, POOL_NAME, NAMESPACE) as rbd:
            disk_name = OS_DISK_PREFIX + vm_name
            rbd.purge_image(disk_name)
            logger.info("Image " + disk_name + " successfully purged")


def rollback_snapshot(vm_name, snapshot_name):
    """
    Restore a VM to a previous state based on the given snapshot.
    :param vm_name: the VM name to be restored
    :param snapshot_name: the snapshot name to be used for rollback
    """

    with RbdManager(CEPH_CONF, POOL_NAME, NAMESPACE) as rbd:

        disk_name = OS_DISK_PREFIX + vm_name
        if not rbd.image_snapshot_exists(disk_name, snapshot_name):
            raise Exception(
                "Snapshot "
                + snapshot_name
                + " does not exist on VM "
                + vm_name
            )

        enabled = is_enabled(vm_name)
        if enabled:
            disable_vm(vm_name)

        rbd.rollback_image(disk_name, snapshot_name)
        logger.info(
            "Image "
            + disk_name
            + " successfully rollbacked to snapshot "
            + snapshot_name
        )

    if enabled:
        enable_vm(vm_name)


def list_metadata(vm_name):
    """
    List all metadata associated to the given VM
    :param vm_name: the VM name from which the metadata will be listed
    :return: the metadata list
    """
    with RbdManager(CEPH_CONF, POOL_NAME, NAMESPACE) as rbd:
        disk_name = OS_DISK_PREFIX + vm_name
        return rbd.list_image_metadata(disk_name)


def get_metadata(vm_name, metadata_name):
    """
    Get a metadata value
    :param vm_name: the VM name where the metadata is stored
    :param metadata_name: the metadata name to get
    :return: the metadata value (a str)
    """
    with RbdManager(CEPH_CONF, POOL_NAME, NAMESPACE) as rbd:
        disk_name = OS_DISK_PREFIX + vm_name
        return rbd.get_image_metadata(disk_name, metadata_name)


def set_metadata(vm_name, metadata_name, metadata_value):
    """
    Set a metadata with the given value. Create it if the metadata does not
    exist yet
    :param vm_name: the VM name where the metadata will be stored
    :param metadata_name: the metadata name to be set
    :param metadata_value: the metadata value to set
    """

    _check_name(metadata_name)
    with RbdManager(CEPH_CONF, POOL_NAME, NAMESPACE) as rbd:
        disk_name = OS_DISK_PREFIX + vm_name
        rbd.set_image_metadata(disk_name, metadata_name, metadata_value)

    logger.info(
        "Image "
        + disk_name
        + " metadata set: ("
        + metadata_name
        + ":"
        + metadata_value
        + ")"
    )


def add_colocation(vm_name, *resources, strong=False):
    """
    Add a colocation constraint to a VM.
    :param vm_name: the VM name to constraint
    :param resources: VMs or other Pacemaker resources to be colocated with the
    VM. The resource must already be created and if the resource is a VM, then
    it must be enabled. Disabling a VM will remove its constraints.
    :param strong: If strong is set to True, add a strong colocation. In a
    strong colocation the VM will be started only if all resources colocated
    with it are started too and the VM will stop if one of them is stopped.
    """
    _check_name(vm_name)
    with Pacemaker(vm_name) as p:
        p.add_colocation(*resources, strong=strong)


def remove_pacemaker_remote(vm_name):
    """
    Remove the pacemaker remote configuration from the VM.
    :param vm_name: the VM name to remove the pacemaker remote configuration
    """
    with RbdManager(CEPH_CONF, POOL_NAME, NAMESPACE) as rbd:
        disk_name = OS_DISK_PREFIX + vm_name
        try:
            rbd.remove_image_metadata(disk_name, "_remote_node")
            rbd.remove_image_metadata(disk_name, "_remote_node_address")
            rbd.remove_image_metadata(disk_name, "_remote_node_port")
            rbd.remove_image_metadata(disk_name, "_remote_node_timeout")
        except KeyError:
            pass
    with Pacemaker(vm_name) as p:
        p.remove_meta("remote-node")
        p.remove_meta("remote-addr")
        p.remove_meta("remote-port")
        p.remove_meta("remote-connect-timeout")


def add_pacemaker_remote(
    vm_name,
    remote_node,
    remote_node_address,
    remote_node_port=None,
    remote_node_timeout=None,
):
    """
    Add a pacemaker-remote configuration to the VM.
    :param vm_name: the VM name to add the pacemaker remote configuration
    :param remote_node: name to identify the pacemaker-remote resource
    :param remote_node_address: the address of the pacemaker-remote resource
    :param remote_node_port: the port of the pacemaker-remote resource
    :param remote_node_timeout: the timeout of the pacemaker-remote resource
    """

    _check_name(remote_node)
    with RbdManager(CEPH_CONF, POOL_NAME, NAMESPACE) as rbd:
        disk_name = OS_DISK_PREFIX + vm_name
        rbd.set_image_metadata(disk_name, "_remote_node", remote_node)
        rbd.set_image_metadata(
            disk_name, "_remote_node_address", remote_node_address
        )
        if remote_node_port:
            rbd.set_image_metadata(
                disk_name, "_remote_node_port", remote_node_port
            )
        if remote_node_timeout:
            rbd.set_image_metadata(
                disk_name, "_remote_node_timeout", remote_node_timeout
            )
    with Pacemaker(vm_name) as p:
        if remote_node_port:
            p.add_meta("remote-port", remote_node_port)
        if remote_node_timeout:
            p.add_meta("remote-connect-timeout", remote_node_timeout)
        p.add_meta("remote-addr", remote_node_address)
        p.add_meta("remote-node", remote_node)
