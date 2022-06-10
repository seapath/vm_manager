# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""
Helper module to manipulate libvirt
"""

import subprocess
import libvirt

import logging

logger = logging.getLogger(__name__)


class LibVirtManager:
    """
    A class to manage libvirt
    """

    def __init__(self):
        """
        ListVirtManager constructor. The constructor opens a connection to
        libvirt through qemu system.
        """
        self._conn = libvirt.open("qemu:///system")

    def __enter__(self):
        """
        Start context
        """
        return self

    def __exit__(self, type, value, traceback):
        """
        Close context
        """
        self.close()

    def close(self):
        """
        Close libvirt context
        """
        self._conn.close()

    def list(self):
        """
        List all VM
        :return the name list of all defined libvirt domain
        """
        return [x.name() for x in self._conn.listAllDomains()]

    def get_virsh_secrets(self):
        """
        Get the virsh secrets
        :return: a dictionary of virsh secrets
        """
        secrets = {}
        for secret in self._conn.listAllSecrets():
            secrets[secret.usageID()] = secret.UUIDString()
        return secrets

    def define(self, xml):
        """
        Validate and create a VM from xml configuration

        Raise an error if the XML is not valid.
        :param xml: the libvirt XML string
        """
        self._conn.defineXMLFlags(xml, libvirt.VIR_DOMAIN_DEFINE_VALIDATE)

    def undefine(self, vm_name):
        """
        Remove a VM
        :param vm_name: the VM to undefined
        """
        domain = self._conn.lookupByName(vm_name)
        domain.undefineFlags(libvirt.VIR_DOMAIN_UNDEFINE_NVRAM)

    def start(self, vm_name):
        """
        Start a VM
        :param vm_name: the VM to start
        """
        self._conn.lookupByName(vm_name).create()

    def stop(self, vm_name):
        """
        Stop a VM
        :param vm_name: the VM to be stopped
        """
        self._conn.lookupByName(vm_name).shutdown()

    @staticmethod
    def export_configuration(domain, xml_path):
        """
        Dump the libvirt XML configuration
        :param domain: the domain whose the configuration is exported
        :param xml_path: the path where the XML configuration will be exported
        """
        subprocess.run(
            "/usr/bin/virsh -c 'qemu:///system' dumpxml {} > {}".format(
                domain, xml_path
            ),
            check=True,
            shell=True,
        )
