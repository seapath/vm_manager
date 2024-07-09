# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

try:
    from .helpers.rbd_manager import RbdManager
    from .helpers.pacemaker import Pacemaker
except ModuleNotFoundError:
    cluster_mode = False
else:
    cluster_mode = True

if cluster_mode:
    from .vm_manager_cluster import (
        list_vms,
        start,
        stop,
        create,
        clone,
        remove,
        enable_vm,
        disable_vm,
        is_enabled,
        status,
        create_snapshot,
        remove_snapshot,
        list_snapshots,
        purge_image,
        rollback_snapshot,
        list_metadata,
        get_metadata,
        set_metadata,
        add_colocation,
        remove_pacemaker_remote,
        add_pacemaker_remote,
    )
else:
    from .vm_manager_libvirt import (
        list_vms,
        create,
        remove,
        start,
        stop,
        status,
    )
