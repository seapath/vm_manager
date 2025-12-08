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
