# Copyright (C) 2026 Savoir-faire Linux Inc.
# SPDX-License-Identifier: Apache-2.0

"""
Generate libvirt domain XML from a dictionary of VM options.

This replaces the need for a pre-existing XML file when creating VMs,
allowing the CLI (and Cockpit webui) to pass individual parameters.
"""

import xml.etree.ElementTree as ET


def generate_xml(options):
    """
    Build a complete ``<domain type="kvm">`` XML string.

    :param options: dict of VM options (see plan for keys)
    :return: XML string
    """
    name = options["name"]
    vcpus = options.get("vcpus", 1)
    cpuset = options.get("cpuset")
    if cpuset:
        vcpus = len(cpuset)
    memory = options.get("memory", 2048)
    description = options.get("description")
    rt = options.get("rt", False)
    rt_priority = options.get("rt_priority", 1)
    emulatorpin = options.get("emulatorpin")
    hugepages = options.get("hugepages", False)
    balloon = options.get("balloon", False)
    vnc = options.get("vnc", False)
    vnc_listen = options.get("vnc_listen", "127.0.0.1")
    secure_boot = options.get("secure_boot", False)
    net_args = options.get("net") or []

    domain = ET.Element("domain", type="kvm")

    # Name and description
    ET.SubElement(domain, "name").text = name
    if description:
        ET.SubElement(domain, "description").text = description

    # vCPUs
    vcpu_el = ET.SubElement(domain, "vcpu", placement="static")
    vcpu_el.text = str(vcpus)

    # Memory
    if hugepages:
        ET.SubElement(domain, "memory", unit="GiB").text = "1"
        ET.SubElement(domain, "currentMemory", unit="GiB").text = "1"
        mb = ET.SubElement(domain, "memoryBacking")
        hp = ET.SubElement(mb, "hugepages")
        ET.SubElement(hp, "page", size="1", unit="G")
        ET.SubElement(mb, "nosharepages")
    else:
        ET.SubElement(domain, "memory", unit="MiB").text = str(memory)
        ET.SubElement(domain, "currentMemory", unit="MiB").text = str(memory)

    # OS
    os_el = ET.SubElement(domain, "os", firmware="efi")
    ET.SubElement(os_el, "type", arch="x86_64", machine="q35").text = "hvm"
    ET.SubElement(os_el, "boot", dev="hd")
    ET.SubElement(os_el, "bootmenu", enable="no")
    ET.SubElement(os_el, "bios", useserial="yes", rebootTimeout="0")
    ET.SubElement(os_el, "smbios", mode="emulate")
    firmware_el = ET.SubElement(os_el, "firmware")
    sb_val = "yes" if secure_boot else "no"
    ET.SubElement(firmware_el, "feature", enabled=sb_val, name="secure-boot")

    # Features
    features = ET.SubElement(domain, "features")
    ET.SubElement(features, "acpi")
    ET.SubElement(features, "apic")
    ET.SubElement(features, "vmport", state="off")
    if rt:
        ET.SubElement(features, "pmu", state="off")

    # CPU tune
    cputune = ET.SubElement(domain, "cputune")
    if cpuset:
        for i, cpu in enumerate(cpuset):
            ET.SubElement(cputune, "vcpupin", vcpu=str(i), cpuset=str(cpu))
            if rt:
                ET.SubElement(
                    cputune,
                    "vcpusched",
                    vcpus=str(i),
                    scheduler="fifo",
                    priority=str(rt_priority),
                )
    if emulatorpin:
        ET.SubElement(cputune, "emulatorpin", cpuset=emulatorpin)

    # CPU model
    if rt:
        cpu_el = ET.SubElement(domain, "cpu", mode="host-passthrough")
        ET.SubElement(
            cpu_el,
            "topology",
            sockets="1",
            dies="1",
            cores=str(vcpus),
            threads="1",
        )
        ET.SubElement(cpu_el, "feature", policy="require", name="tsc-deadline")
    else:
        cpu_el = ET.SubElement(
            domain, "cpu", mode="host-model", check="partial"
        )
        ET.SubElement(cpu_el, "model", fallback="allow")

    # NUMA cell for hugepages
    if hugepages:
        numa = ET.SubElement(cpu_el, "numa")
        cpus_str = "0-{}".format(vcpus - 1) if vcpus > 1 else "0"
        ET.SubElement(
            numa,
            "cell",
            id="0",
            cpus=cpus_str,
            memory="1",
            unit="GiB",
            memAccess="shared",
        )

    # Clock
    clock = ET.SubElement(domain, "clock", offset="utc")
    ET.SubElement(clock, "timer", name="rtc", tickpolicy="catchup")
    ET.SubElement(clock, "timer", name="pit", tickpolicy="delay")
    ET.SubElement(clock, "timer", name="hpet", present="no")

    # Power management
    ET.SubElement(domain, "on_poweroff").text = "destroy"
    ET.SubElement(domain, "on_reboot").text = "restart"
    ET.SubElement(domain, "on_crash").text = "destroy"
    pm = ET.SubElement(domain, "pm")
    ET.SubElement(pm, "suspend-to-mem", enabled="no")
    ET.SubElement(pm, "suspend-to-disk", enabled="no")

    # Devices
    devices = ET.SubElement(domain, "devices")
    ET.SubElement(devices, "emulator").text = "/usr/bin/qemu-system-x86_64"

    # VNC
    if vnc:
        gfx = ET.SubElement(
            devices,
            "graphics",
            type="vnc",
            port="-1",
            autoport="yes",
            listen=vnc_listen,
        )
        ET.SubElement(gfx, "listen", type="address", address=vnc_listen)
        video = ET.SubElement(devices, "video")
        ET.SubElement(video, "model", type="virtio", heads="1", primary="yes")
        ET.SubElement(devices, "input", type="tablet", bus="usb")

    # Network interfaces
    for net_str in net_args:
        net_dict = _parse_net_arg(net_str)
        _add_net_to_devices(devices, net_dict)

    # Standard controllers / serial / console
    ET.SubElement(
        devices, "controller", type="pci", index="0", model="pcie-root"
    )
    serial = ET.SubElement(devices, "serial", type="pty")
    target = ET.SubElement(serial, "target", type="isa-serial", port="0")
    ET.SubElement(target, "model", name="isa-serial")
    console = ET.SubElement(devices, "console", type="pty")
    ET.SubElement(console, "target", type="serial", port="0")

    # Memballoon
    if balloon:
        mb_el = ET.SubElement(devices, "memballoon", model="virtio")
        ET.SubElement(mb_el, "stats", period="5")
    else:
        ET.SubElement(devices, "memballoon", model="none")

    # Watchdog
    ET.SubElement(devices, "watchdog", model="i6300esb", action="poweroff")

    ET.indent(domain)
    return ET.tostring(domain, encoding="unicode", xml_declaration=False)


def _parse_net_arg(net_str):
    """
    Parse a ``--net`` CLI value into a dict.

    Format: ``type=bridge,source=br0,mac=52:54:00:00:00:01,vlan=100``

    :param net_str: comma-separated key=value string
    :return: dict with parsed keys
    :raises ValueError: on missing required keys or unknown type
    """
    pairs = net_str.split(",")
    d = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(
                "Invalid net argument '{}': expected key=value".format(pair)
            )
        key, value = pair.split("=", 1)
        d[key] = value

    net_type = d.get("type")
    if not net_type:
        raise ValueError("Missing 'type' in --net argument")

    required = {
        "bridge": ["source", "mac"],
        "macvtap": ["source", "mac"],
        "pci": ["address"],
        "sriov": ["network"],
        "ovs": ["mac", "port"],
    }
    if net_type not in required:
        raise ValueError("Unknown network type '{}'".format(net_type))

    for key in required[net_type]:
        if key not in d:
            raise ValueError(
                "Missing required key '{}' for network type '{}'".format(
                    key, net_type
                )
            )

    return d


def _add_net_to_devices(devices, net_dict):
    """
    Add XML elements for one network interface to ``<devices>``.

    :param devices: the ``<devices>`` Element
    :param net_dict: parsed dict from :func:`_parse_net_arg`
    """
    net_type = net_dict["type"]

    if net_type == "bridge":
        iface = ET.SubElement(devices, "interface", type="bridge")
        ET.SubElement(iface, "source", bridge=net_dict["source"])
        ET.SubElement(iface, "mac", address=net_dict["mac"])
        ET.SubElement(iface, "model", type="virtio")
        if "virtualport" in net_dict:
            ET.SubElement(iface, "virtualport", type=net_dict["virtualport"])
        if "vlan" in net_dict:
            vlan_el = ET.SubElement(iface, "vlan")
            ET.SubElement(vlan_el, "tag", id=net_dict["vlan"])

    elif net_type == "macvtap":
        attrs = {"type": "direct"}
        if net_dict.get("trust_guest_rx"):
            attrs["trustGuestRxFilters"] = "yes"
        iface = ET.SubElement(devices, "interface", **attrs)
        src_attrs = {"dev": net_dict["source"]}
        if "mode" in net_dict:
            src_attrs["mode"] = net_dict["mode"]
        ET.SubElement(iface, "source", **src_attrs)
        ET.SubElement(iface, "mac", address=net_dict["mac"])
        ET.SubElement(iface, "model", type="virtio")

    elif net_type == "pci":
        addr = net_dict["address"]
        parts = addr.replace(".", ":").split(":")
        if len(parts) != 4:
            raise ValueError(
                "PCI address must be DDDD:BB:SS.F, got '{}'".format(addr)
            )
        hostdev = ET.SubElement(
            devices,
            "hostdev",
            mode="subsystem",
            type="pci",
            managed="yes",
        )
        source = ET.SubElement(hostdev, "source")
        ET.SubElement(
            source,
            "address",
            domain="0x" + parts[0],
            bus="0x" + parts[1],
            slot="0x" + parts[2],
            function="0x" + parts[3],
        )

    elif net_type == "sriov":
        iface = ET.SubElement(devices, "interface", type="network")
        ET.SubElement(iface, "source", network=net_dict["network"])

    elif net_type == "ovs":
        iface = ET.SubElement(devices, "interface", type="ethernet")
        ET.SubElement(iface, "mac", address=net_dict["mac"])
        ET.SubElement(iface, "target", dev=net_dict["port"], managed="no")
        ET.SubElement(iface, "model", type="virtio")
