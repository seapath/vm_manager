# Copyright (C) 2026 Savoir-faire Linux Inc.
# SPDX-License-Identifier: Apache-2.0

import os
import sys

sys.path.insert(0, os.path.abspath(".."))

project = "vm_manager"
copyright = "2026, Savoir-faire Linux Inc, RTE (http://www.rte-france.com) and contributors"
author = "Mathieu Dupré"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
    "sphinxarg.ext",
]

# Mock imports for optional dependencies unavailable at doc build time
autodoc_mock_imports = [
    "libvirt",
    "rados",
    "rbd",
    "flask",
    "flask_wtf",
]

html_theme = "alabaster"
