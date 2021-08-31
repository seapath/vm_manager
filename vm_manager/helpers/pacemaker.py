# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""
Helper module to manipulate Pacemaker.
"""

import subprocess
import logging
import threading

logger = logging.getLogger(__name__)


class PacemakerException(Exception):
    """
    A class to catch Pacemaker exceptions
    """


class Pacemaker:
    """
    Helper class to manipulate Pacemaker.
    """

    def __init__(self, resource):
        """
        Class constructor.
        """
        self._resource = resource

    def __enter__(self):
        """
        Start context.
        """
        logger.info("Start context")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """
        Close context.
        """
        logger.info("Exiting context")

    def set_resource(self, resource):
        """
        Setter for variable resource
        """
        self._resource = resource

    def get_resource(self, resource):
        """
        Getter for variable resource
        """
        return self._resource

    def _run_crm_resource(self, cmd, *args):
        """
        Executes $ crm_resource followed by the command cmd and the
        arguments args on the resource _resource.
        """
        command = (
            ["/usr/bin/crm", "resource"]
            + [cmd]
            + list(args)
            + [self._resource]
        )
        logger.info("Execute: " + (str(subprocess.list2cmdline(command))))
        subprocess.run(command, check=True)

    def start(self):
        """
        Starts resource and anything that depends on it.
        """
        self._run_crm_resource("start")

    def stop(self):
        """
        Stops resource and anything that depends on it.
        """
        self._run_crm_resource("stop")

    def restart(self):
        """
        Restarts resource and anything that depends on it.
        """
        self._run_crm_resource("restart")

    def force_stop(self):
        """
        Bypasses the cluster and stop a resource on the local node.
        """
        args = [
            "/usr/bin/crm_resource",
            "--force-stop",
            "--resource",
            self._resource,
        ]
        logger.info("Execute: " + (str(subprocess.list2cmdline(args))))
        subprocess.run(args, check=True)

    def cleanup(self):
        """
        Deletes the resource history and re-checks the current state.
        """
        self._run_crm_resource("cleanup")

    @staticmethod
    def list_resources():
        """
        List node resources.
        """
        args = [
            "/usr/bin/crm",
            "resource",
            "list",
        ]
        output_cmd = subprocess.run(args, check=True, capture_output=True)
        output = output_cmd.stdout.decode()

        resources = []
        if "NO resources configured" in output:
            return resources

        for line in output.split("\n"):
            if line:
                resources += [line.split("\t")[0].strip()]
        return resources

    def delete(self, force=False):
        """
        Deletes one or more objects. Use force parameter to delete started
        resources.
        """
        args = (
            [
                "/usr/bin/crm",
                "configure",
                "delete",
            ]
            + (["--force"] if force else [])
            + [self._resource]
        )
        logger.info("Execute: " + (str(subprocess.list2cmdline(args))))
        subprocess.run(args, check=True)

    def show(self):
        """
        Show Cluster Information Base for _resource.
        """
        args = [
            "/usr/bin/crm",
            "resource",
            "show",
        ]
        output = subprocess.run(args, check=True, capture_output=True)
        output_list = output.stdout.decode("utf-8").split("\n")

        for line in output_list:
            if line:
                resource, _, status = line.split("\t")
                resource = resource.strip(" ")
                if resource == self._resource:
                    return status.split(" ")[0]

    @staticmethod
    def status():
        """
        Show cluster status.
        """
        subprocess.run(
            ["/usr/bin/crm", "status"],
            check=True,
        )

    def add_vm(
        self,
        xml,
        start_timeout=120,
        stop_timeout=120,
        monitor_timeout=30,
        monitor_interval=10,
        is_managed=True,
        force_stop=True,
        remote_node="",
        seapath_managed=True,
    ):
        """
        Add VM to Pacemaker cluster.
        """
        is_managed = "is-managed=" + "'true'" if is_managed else "'false'"

        enable_force_stop = (
            "force_stop=" + "'true'" if force_stop else "'false'"
        )

        r_node = ["remote-node=" + remote_node] if remote_node != "" else []

        args = [
            "/usr/bin/crm",
            "configure",
            "primitive",
            self._resource,
            "ocf:heartbeat:VirtualDomain",
            enable_force_stop,
            "params",
            "config=" + xml,
            "hypervisor='qemu:///system'",
            "migration_transport='ssh'",
            "seapath='{}'".format("true" if seapath_managed else "false"),
            "meta",
            "allow-migrate='true'",
            is_managed,
            "op",
            "start",
            "timeout='" + str(start_timeout) + "'",
            "op",
            "stop",
            "timeout='" + str(stop_timeout) + "'",
            "op",
            "monitor",
            "timeout='" + str(monitor_timeout) + "'",
            "interval='" + str(monitor_interval) + "'",
        ] + r_node

        logger.info("Execute: " + (str(subprocess.list2cmdline(args))))
        subprocess.run(args, check=True)

    def set_location(self, node):
        """
        Define on which nodes a resource must be run.
        Note: It will be used to restrict the VM on the hypervisors.
        TODO: NOT TESTED
        """
        args = [
            "/usr/bin/crm",
            "configure",
            "location",
            "no-probe",
            self._resource,
            "resource-discovery=never",
            "-inf: " + str(node),
        ]

        subprocess.run(args, check=True)

    def wait_for(self, state, periods=0.2, nb_periods=100):
        """
        Wait for a VM enter in the given state
        Check every period in s.
        """
        ticker = threading.Event()
        while not ticker.wait(periods) and nb_periods > 0:
            if self.show() == state:
                return
            nb_periods -= 1
        raise PacemakerException("Timeout")
