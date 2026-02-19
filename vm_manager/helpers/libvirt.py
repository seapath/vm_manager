# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""
Helper module to manipulate libvirt
"""

import subprocess
import sys
import libvirt

import logging

logger = logging.getLogger(__name__)


class LibVirtManager:
    """
    A class to manage libvirt
    """

    def __init__(self, uri="qemu:///system"):
        """
        ListVirtManager constructor. The constructor opens a connection to
        libvirt through qemu system.
        """
        self._conn = libvirt.open(uri)

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
        try:
            self._conn.defineXMLFlags(xml, libvirt.VIR_DOMAIN_DEFINE_VALIDATE)
        except libvirt.libvirtError as e:
            logging.error(f"Error with xml configure: {xml}")
            raise e

    def undefine(self, vm_name):
        """
        Remove a VM
        :param vm_name: the VM to undefined
        """
        domain = self._conn.lookupByName(vm_name)
        domain.undefineFlags(libvirt.VIR_DOMAIN_UNDEFINE_NVRAM)

    def set_autostart(self, vm_name, enabled):
        """
        Set the autostart flag on a VM
        :param vm_name: the VM name
        :param enabled: True to enable autostart, False to disable
        """
        self._conn.lookupByName(vm_name).setAutostart(1 if enabled else 0)

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

    def force_stop(self, vm_name):
        """
        Forces a VM to stop
        :param vm_name: the VM to be stopped
        """
        self._conn.lookupByName(vm_name).destroy()

    def status(self, vm_name):
        """
        Get the VM status
        :param vm_name: the VM for which the status must be checked
        :return:    the status of the VM, among Starting, Started, Paused,
                    Stopped, Stopping, Undefined and FAILED
        """
        if vm_name not in self.list():
            logger.info(vm_name + "does not exist")
            return "Undefined"
        else:
            state = self._conn.lookupByName(vm_name).state()[0]
            if state == libvirt.VIR_DOMAIN_NOSTATE:
                return "Undefined"
            elif state == libvirt.VIR_DOMAIN_RUNNING:
                return "Started"
            elif state == libvirt.VIR_DOMAIN_BLOCKED:
                return "Paused"
            elif state == libvirt.VIR_DOMAIN_PAUSED:
                return "Paused"
            elif state == libvirt.VIR_DOMAIN_SHUTDOWN:
                return "Stopping"
            elif state == libvirt.VIR_DOMAIN_SHUTOFF:
                return "Stopped"
            elif state == libvirt.VIR_DOMAIN_CRASHED:
                return "FAILED"
            elif state == libvirt.VIR_DOMAIN_PMSUSPENDED:
                return "Paused"
            else:
                return "Undefined"

    def console(self, vm_name):
        """
        Open a console on a VM
        :param vm_name: the VM to open the console
        """
        uri = self._conn.getURI()
        command = ["/usr/bin/virsh", "-c", uri, "console", vm_name]
        logger.debug("Run: " + " ".join(command))
        try:
            subprocess.run(
                command,
                check=True,
                stdin=sys.stdin,
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
        except subprocess.CalledProcessError:
            pass

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
