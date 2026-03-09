CLI Reference
=============

vm_manager_cmd
--------------

Main CLI tool for VM management. Available subcommands depend on the
operating mode (standalone or cluster) detected at runtime.

.. argparse::
   :module: vm_manager.vm_manager_cmd
   :func: get_parser
   :prog: vm_manager_cmd

libvirt_cmd
-----------

Lower-level CLI for direct libvirt operations.

.. argparse::
   :module: vm_manager.helpers.libvirt_cmd
   :func: get_parser
   :prog: libvirt_cmd
