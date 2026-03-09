# Copyright (C) 2025, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0


class VmManagerException(Exception):
    """Base exception for vm_manager errors."""


class UuidConflictError(VmManagerException):
    """Raised when a VM UUID conflicts with an existing VM."""
