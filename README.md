[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=seapath_vm_manager&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=seapath_vm_manager)

# VM Manager

The purpose of this tool is to easily manage Virtual Machines (VM) on a Hypervisor.
This tool allows to:
- manage VM on standalone serveur with KVM
- manage VM on a cluster with Pacemaker (running on top of KVM)

This tool takes as input VM image (qcow2) and configuration (libvirt XML file)
