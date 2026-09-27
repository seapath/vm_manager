# Copyright (C) 2026, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

from unittest import mock

from vm_manager.helpers.pacemaker import Pacemaker


def test_default_location_writes_a_named_constraint():
    with mock.patch("subprocess.run") as run:
        Pacemaker("vm1").default_location("node2")

    run.assert_called_once_with(
        [
            "crm",
            "configure",
            "location",
            "seapath-preferred-vm1",
            "vm1",
            "inf:",
            "node2",
        ],
        check=True,
    )
