# Copyright (C) 2021, RTE (http://www.rte-france.com)
# Copyright (C) 2024 Savoir-faire Linux Inc.
# SPDX-License-Identifier: Apache-2.0

"""
Helper module to manipulate Pacemaker.
"""

import subprocess
import logging
import threading
import re

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
        Setter for variable resource.
        """
        self._resource = resource

    def get_resource(self):
        """
        Getter for variable resource.
        """
        return self._resource

    def _run_crm_resource(self, cmd, *args):
        """
        Executes $ crm_resource followed by the command cmd and the
        arguments args on the resource _resource.
        """
        command = ["crm", "resource"] + [cmd] + list(args) + [self._resource]
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
            "crm_resource",
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
            "crm",
            "resource",
            "status",
        ]
        output_cmd = subprocess.run(args, check=False, capture_output=True)
        output = output_cmd.stdout.decode()

        resources = []
        if "NO resources configured" in output or "No resources" in output:
            return resources

        for line in output.split("\n"):
            if re.match(r".*ocf::?seapath:VirtualDomain.*", line):
                resources += [
                    line.split("\t")[0].replace("*", "").replace(" ", "")
                ]
        return resources

    def delete(self, force=False, clean=False):
        """
        Deletes one or more objects. Use force parameter to delete started
        resources.
        """
        if clean:
            args = [
                "crm",
                "resource",
                "clean",
            ]
            logger.info("Execute: " + (str(subprocess.list2cmdline(args))))
            subprocess.run(args, check=True)

        args = (
            [
                "crm",
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
            "crm",
            "resource",
            "status",
        ]
        output = subprocess.run(args, check=True, capture_output=True)
        output_list = output.stdout.decode("utf-8").split("\n")

        for line in output_list:
            if re.match(r".*ocf::?seapath:VirtualDomain.*", line):
                try:
                    resource, _, status = line.split("\t")
                    resource = resource.replace("*", "").replace(" ", "")
                    if resource == self._resource:
                        return status.lstrip()
                except ValueError:
                    pass

    @staticmethod
    def status():
        """
        Show cluster status.
        """
        subprocess.run(
            ["crm", "status"],
            check=True,
        )

    def add_vm(self, vm_options):
        """
        Add VM to Pacemaker cluster.
        """

        command_args = [
            "crm",
            "configure",
            "primitive",
            self._resource,
            "ocf:seapath:VirtualDomain",
        ]
        params_args = [
            "params",
            "force_stop=" + str(vm_options.get("force_stop", False)).lower(),
            "migration_downtime="
            + str(vm_options.get("migration_downtime", 0)),
            "config=" + vm_options["xml"],
            "hypervisor='qemu:///system'",
            "seapath='{}'".format(
                str(vm_options.get("seapath_managed", False)).lower()
            ),
            "migration_transport=ssh",
            "migration_user='"
            + vm_options.get("migration_user", "root")
            + "'",
        ]
        if vm_options.get("custom_params"):
            for key, value in vm_options["custom_params"].items():
                params_args.append(f"{key}='{value}'")

        meta_args = [
            "meta",
            "allow-migrate='"
            + str(vm_options.get("live_migration", False)).lower()
            + "'",
            "is-managed=" + str(vm_options.get("is_managed", True)).lower(),
            "priority='" + vm_options.get("priority", "0") + "'",
        ]
        if vm_options.get("custom_meta"):
            for key, value in vm_options["custom_meta"].items():
                meta_args.append(f"{key}='{value}'")

        op_args = [
            "op",
            "start",
            "timeout='" + vm_options.get("start_timeout", "120") + "'",
            "op",
            "stop",
            "timeout='" + vm_options.get("stop_timeout", "30") + "'",
            "op",
            "migrate_from",
            "timeout='" + vm_options.get("migrate_from_timeout", "60") + "'",
            "op",
            "migrate_to",
            "timeout='" + vm_options.get("migrate_to_timeout", "120") + "'",
            "op",
            "monitor",
            "timeout='" + vm_options.get("monitor_timeout", "60") + "'",
            "interval='" + vm_options.get("monitor_interval", "10") + "'",
        ]
        utilization_args = []
        if vm_options.get("custom_utilization"):
            utilization_args.append("utilization")
            for key, value in vm_options["custom_utilization"].items():
                utilization_args.append(f"{key}='{value}'")
        args = (
            command_args + params_args + meta_args + op_args + utilization_args
        )

        if vm_options.get("pacemaker_remote"):
            args += [
                "meta",
                "remote-node='" + vm_options["pacemaker_remote"] + "'",
            ]
            if vm_options.get("pacemaker_remote_addr"):
                args += [
                    "remote-addr='" + vm_options["pacemaker_remote_addr"] + "'"
                ]
            if vm_options.get("pacemaker_remote_port"):
                args += [
                    "remote-port='" + vm_options["pacemaker_remote_port"] + "'"
                ]
            if vm_options.get("pacemaker_remote_timeout"):
                args += [
                    "remote-connect-timeout='"
                    + vm_options["pacemaker_remote_timeout"]
                    + "'"
                ]

        logger.info("Execute: " + (str(subprocess.list2cmdline(args))))
        subprocess.run(args, check=True)

    def manage(self):
        """
        Manage a VM by Pacemaker.
        """
        subprocess.run(
            ["crm", "resource", "manage", self._resource], check=True
        )

    def disable_location(self, node):
        """
        Define on which nodes a resource must never be run.
        Note: It will be used to restrict the VM on the hypervisors.
        """
        args = [
            "crm",
            "resource",
            "ban",
            self._resource,
            node,
        ]

        subprocess.run(args, check=True)

    def pin_location(self, node):
        """
        Pin a VM on a node.
        """
        args = [
            "crm",
            "configure",
            "location",
            f"pin-{self._resource}-on{node}",
            self._resource,
            "resource-discovery=exclusive",
            "inf:",
            node,
        ]

        subprocess.run(args, check=True)

    def add_colocation(self, *resources, strong=False):
        """
        Group a VM with other resources
        """
        if not resources:
            raise Exception("At least one resource is needed")
        args = [
            "crm",
            "configure",
            "colocation",
            f"colocation-{'strong-' if strong else ''}{self._resource}"
            f"-with{'-'.join(resources)}",
            f"{'inf' if strong else '700'}:",
            self._resource,
            "(",
        ]

        args += resources
        args.append(")")

        subprocess.run(args, check=True)

    def default_location(self, node):
        """
        Set the VM default location. The VM will be deployed on the given node
        unless the node is up.
        """
        args = [
            "crm",
            "resource",
            "move",
            self._resource,
            node,
        ]

        subprocess.run(args, check=True)

    def wait_for(self, state, periods=0.2, nb_periods=100):
        """
        Wait for a VM enter the given state.
        Check every period in s.
        """
        ticker = threading.Event()
        while not ticker.wait(periods) and nb_periods > 0:
            if self.show() == state:
                return
            nb_periods -= 1
        raise PacemakerException("Timeout")

    def run_crm_cmd(self, cmd):
        """
        Run a crm configure command
        """
        # Do not run empty command otherwise crm enter in crm configure
        # interactive mode and block the execution
        if not cmd:
            return
        args = [
            "crm",
            "configure",
        ]
        args.extend(cmd.split(" "))

        subprocess.run(args, check=True)

    def add_meta(self, key, value):
        """
        Add a meta to the resource
        :param meta: the meta to add
        """
        args = ["crm", "resource", "meta", self._resource, "set", key, value]

        subprocess.run(args, check=True)

    def remove_meta(self, key):
        """
        Remove a meta from the resource
        :param meta: the meta to remove
        """
        args = [
            "crm",
            "resource",
            "meta",
            self._resource,
            "delete",
            key,
        ]

        subprocess.run(args, check=True)

    @staticmethod
    def is_valid_host(host):
        """
        Check if a host is found in the cluster.
        :param host: the host to test
        :return: True if the host is in the cluster, false otherwise
        """
        command = "bash -c \"grep -E '^" + host + "$' <(crm node server)\""
        ret = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE)
        ret.wait()
        return ret.returncode == 0
