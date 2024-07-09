# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

from setuptools import setup, find_packages

setup(
    name="vm_manager",
    version="0.1",
    packages=find_packages(),
    url="https://github.com/seapath/vm_manager",
    author="RTE",
    license="Apache License 2.0",
    author_email="mathieu.dupre@savoirfairelinux.com",
    description="Managed VMs in Seapath cluster",
    include_package_data=True,
    install_requires=["flask", "Flask-WTF"],
    scripts=[
        "vm_manager/helpers/libvirt_cmd.py",
        "vm_manager/helpers/tests/pacemaker/add_vm.py",
        "vm_manager/helpers/tests/pacemaker/remove_vm.py",
        "vm_manager/helpers/tests/pacemaker/start_vm.py",
        "vm_manager/helpers/tests/pacemaker/stop_vm.py",
        "vm_manager/helpers/tests/rbd_manager/clone_rbd.py",
        "vm_manager/helpers/tests/rbd_manager/create_rbd_group.py",
        "vm_manager/helpers/tests/rbd_manager/metadata_rbd.py",
        "vm_manager/helpers/tests/rbd_manager/create_rbd_namespace.py",
        "vm_manager/helpers/tests/rbd_manager/purge_rbd.py",
        "vm_manager/helpers/tests/rbd_manager/rollback_rbd.py",
        "vm_manager/helpers/tests/rbd_manager/write_rbd.py",
        "vm_manager_cmd.py",
    ],
)
