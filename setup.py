# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

from setuptools import setup, find_packages

setup(
    name="vm_manager",
    version="0.1",
    packages=find_packages(),
    url="https://g1.sfl.team/plugins/gitiles/rte/votp/vm_manager",
    license="CLOSED",
    author="Apache License 2.0",
    author_email="mathieu.dupre@savoirfairelinux.com",
    description="Managed VMs in Seapath cluster",
    include_package_data=True,
)
