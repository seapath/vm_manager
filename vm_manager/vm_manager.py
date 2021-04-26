# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""
A module to manage VMs in Seapath cluster.
"""


def list_vms():
    """
    List all the VM
    :return: the VM list
    """
    return []


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


def remove(vm_name):
    """
    Remove a VM from cluster
    :param vm_name: the VM name to be removed
    """


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
