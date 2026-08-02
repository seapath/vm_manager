# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**vm_manager** is a Python tool for managing Virtual Machines on the SEAPATH platform. It operates in two modes, auto-detected at import time (`__init__.py`):
- **Standalone mode** (`vm_manager_libvirt.py`): manages VMs via KVM/libvirt only
- **Cluster mode** (`vm_manager_cluster.py`): manages VMs on a Pacemaker HA cluster with Ceph RBD storage

## Build & Install

```bash
# Install locally (or use cqfd for containerized builds)
pip install .

# Using cqfd (Docker-based build wrapper, config in .cqfdrc)
cqfd
```

## Linting & Formatting

```bash
# Format with Black (line length 79, Python 3.8 target)
black -l 79 -t py38 .

# Check formatting without modifying
black -l 79 -t py38 --check .

# Flake8
python3 -m flake8 --ignore=E501,W503

# Pylint
pylint pacemaker_helper rbd_helper vm_manager

# Via cqfd flavors
cqfd -b check_format   # check formatting
cqfd -b format          # auto-format
cqfd -b flake           # flake8
cqfd -b check           # pylint
```

## Documentation

```bash
# Generate HTML docs locally (output: docs/_build/html/)
pip install .[docs]
sphinx-build -b html docs docs/_build/html

# Via cqfd
cqfd init
cqfd -b docs
```

Docs structure: `docs/overview.rst` (project overview), `docs/cli.rst`
(CLI reference via sphinx-argparse), `docs/api.rst` (Python API via autodoc).
sphinx-argparse requires `get_parser()` functions in both CLI modules.

## Tests

The pytest suite lives in `tests/`:

```bash
pip install .[test]

# Everything (needs a real Ceph/Pacemaker cluster)
pytest tests/

# What CI runs: no cluster needed
pytest tests/ \
    --ignore=tests/test_vm_manager_cluster.py \
    --ignore=tests/test_vm_manager_cmd_cluster.py
```

`tests/conftest.py` calls `install_ceph_stubs()` from `tests/ceph_stubs.py`
**before** importing vm_manager. vm_manager picks its backend at import time
(`__init__.py`), so without the stubs `cluster_mode` is False on any machine
without Ceph and all cluster-side tests are skipped, even the ones that need
no cluster. The stubs raise on use, so a test that reaches real Ceph code
fails loudly. Anything genuinely needing a cluster belongs in
`test_vm_manager_cluster.py` or `test_vm_manager_cmd_cluster.py`, which CI
ignores.

Older standalone integration scripts, run by hand against a real cluster,
live in `vm_manager/helpers/tests/pacemaker/` and
`vm_manager/helpers/tests/rbd_manager/`:

```bash
python3 -m vm_manager.helpers.tests.rbd_manager.clone_rbd
python3 -m vm_manager.helpers.tests.pacemaker.add_vm
```

## Architecture

**Entry points** (defined in `pyproject.toml [project.scripts]`):
- `vm_manager_cmd` — CLI (argparse) exposing all VM operations as subcommands
- `libvirt_cmd` — Standalone CLI for libvirt-only operations
- `vm_manager_api.py` — Flask REST API (`/`, `/status/<guest>`, `/stop/<guest>`, `/start/<guest>`)

**Mode selection** (`__init__.py`): tries to import `RbdManager` and `Pacemaker`. If both succeed, public API functions (`list_vms`, `create`, `remove`, `start`, `stop`, etc.) come from `vm_manager_cluster.py`; otherwise from `vm_manager_libvirt.py`.

**Helper classes** (all used as context managers with `with` statements):
- `LibVirtManager` (`helpers/libvirt.py`): wraps `libvirt-python` for domain management
- `Pacemaker` (`helpers/pacemaker.py`): wraps `crm` CLI via `subprocess.run()`
- `RbdManager` (`helpers/rbd_manager.py`): wraps Ceph `rados`/`rbd` Python bindings

## Conventions

- **Python target**: 3.8+
- **Line length**: 79 characters
- **License**: Apache-2.0 (all source files have copyright headers)
- **Code review**: Gerrit (`.gitreview` → `g1.sfl.team`)
- **VM naming**: alphanumeric only, validated by `_check_name()`
- **Disk naming**: system disks prefixed with `system_` (`OS_DISK_PREFIX`), additional disks prefixed with `data_` (`DATA_DISK_PREFIX`), e.g. `data_guest0_0`
- **Flake8 config** (`.flake8`): ignores F401 in `__init__.py`, E501 and W503 globally
- **Custom exceptions**: `RbdException`, `PacemakerException`
