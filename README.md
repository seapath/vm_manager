[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=seapath_vm_manager&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=seapath_vm_manager)

# VM Manager

The purpose of this tool is to easily manage Virtual Machines (VM) on a Hypervisor.
This tool allows to:
- manage VM on a standalone server with KVM
- manage VM on a cluster with Pacemaker (running on top of KVM)

This tool takes as input VM image (qcow2) and configuration (libvirt XML file)

## Dependencies

To run vm_manager on your machine for development, the following packages must be installed:

On Debian
```
sudo apt-get install python3 python3-libvirt python-rbd python3-flaskext.wtf
```

On Fedora/RHEL
```
sudo dnf install python3 python3-libvirt python3-rbd python3-flask-wtf
```

All theses dependencies are satisfied on a SEAPATH machine.

## Tests

The test suite uses pytest and requires libvirt/QEMU to be available on the host.

### Install test dependencies

```bash
pip install .[test]
```

### Run all tests

```bash
pytest tests/
```

### Run only standalone tests (no cluster required)

The cluster tests (`test_vm_manager_cluster.py`) require a running Pacemaker/Ceph
cluster. To run only the standalone libvirt tests, exclude that file:

```bash
pytest tests/ --ignore=tests/test_vm_manager_cluster.py
```

## Documentation

The HTML documentation is generated with Sphinx.

### Install documentation dependencies

```bash
pip install .[docs]
```

### Build the documentation

```bash
sphinx-build -b html docs docs/_build/html
```

The generated documentation is available at `docs/_build/html/index.html`.

Alternatively, using cqfd (Docker-based build wrapper):

```bash
cqfd init
cqfd -b docs
```
