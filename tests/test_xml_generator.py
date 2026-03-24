# Copyright (C) 2026 Savoir-faire Linux Inc.
# SPDX-License-Identifier: Apache-2.0

import xml.etree.ElementTree as ET

import pytest

from vm_manager.xml_generator import (
    generate_xml,
    _parse_net_arg,
)


def _parse(xml_str):
    return ET.fromstring(xml_str)


class TestMinimalXml:
    def test_domain_type(self):
        root = _parse(generate_xml({"name": "testvm"}))
        assert root.tag == "domain"
        assert root.get("type") == "kvm"

    def test_name(self):
        root = _parse(generate_xml({"name": "testvm"}))
        assert root.findtext("name") == "testvm"

    def test_no_uuid(self):
        root = _parse(generate_xml({"name": "testvm"}))
        assert root.find("uuid") is None

    def test_default_vcpus(self):
        root = _parse(generate_xml({"name": "testvm"}))
        assert root.findtext("vcpu") == "1"

    def test_default_memory(self):
        root = _parse(generate_xml({"name": "testvm"}))
        assert root.findtext("memory") == "2048"
        assert root.find("memory").get("unit") == "MiB"

    def test_devices_present(self):
        root = _parse(generate_xml({"name": "testvm"}))
        devices = root.find("devices")
        assert devices is not None
        assert devices.findtext("emulator") == ("/usr/bin/qemu-system-x86_64")

    def test_memballoon_none_by_default(self):
        root = _parse(generate_xml({"name": "testvm"}))
        mb = root.find("devices/memballoon")
        assert mb.get("model") == "none"

    def test_watchdog(self):
        root = _parse(generate_xml({"name": "testvm"}))
        wd = root.find("devices/watchdog")
        assert wd is not None
        assert wd.get("model") == "i6300esb"

    def test_os_firmware(self):
        root = _parse(generate_xml({"name": "testvm"}))
        os_el = root.find("os")
        assert os_el.get("firmware") == "efi"
        assert os_el.find("type").text == "hvm"
        assert os_el.find("type").get("machine") == "q35"

    def test_secure_boot_disabled_by_default(self):
        root = _parse(generate_xml({"name": "testvm"}))
        feat = root.find("os/firmware/feature")
        assert feat.get("name") == "secure-boot"
        assert feat.get("enabled") == "no"

    def test_clock(self):
        root = _parse(generate_xml({"name": "testvm"}))
        clock = root.find("clock")
        assert clock.get("offset") == "utc"

    def test_pcie_root(self):
        root = _parse(generate_xml({"name": "testvm"}))
        ctrl = root.find("devices/controller[@type='pci']")
        assert ctrl.get("model") == "pcie-root"

    def test_serial_console(self):
        root = _parse(generate_xml({"name": "testvm"}))
        assert root.find("devices/serial") is not None
        assert root.find("devices/console") is not None

    def test_no_pmu_by_default(self):
        root = _parse(generate_xml({"name": "testvm"}))
        assert root.find("features/pmu") is None

    def test_cpu_host_model_by_default(self):
        root = _parse(generate_xml({"name": "testvm"}))
        cpu = root.find("cpu")
        assert cpu.get("mode") == "host-model"


class TestDescription:
    def test_description_set(self):
        root = _parse(generate_xml({"name": "vm", "description": "My VM"}))
        assert root.findtext("description") == "My VM"

    def test_no_description_by_default(self):
        root = _parse(generate_xml({"name": "vm"}))
        assert root.find("description") is None


class TestRtOptions:
    def setup_method(self):
        self.root = _parse(
            generate_xml(
                {
                    "name": "rtvm",
                    "rt": True,
                    "cpuset": [2, 3],
                    "rt_priority": 5,
                    "emulatorpin": "0,1",
                }
            )
        )

    def test_cpu_mode(self):
        cpu = self.root.find("cpu")
        assert cpu.get("mode") == "host-passthrough"

    def test_topology(self):
        topo = self.root.find("cpu/topology")
        assert topo.get("cores") == "2"
        assert topo.get("sockets") == "1"

    def test_tsc_deadline(self):
        feat = self.root.find("cpu/feature")
        assert feat.get("name") == "tsc-deadline"

    def test_pmu_off(self):
        pmu = self.root.find("features/pmu")
        assert pmu.get("state") == "off"

    def test_vcpupin(self):
        pins = self.root.findall("cputune/vcpupin")
        assert len(pins) == 2
        assert pins[0].get("cpuset") == "2"
        assert pins[1].get("cpuset") == "3"

    def test_vcpusched(self):
        scheds = self.root.findall("cputune/vcpusched")
        assert len(scheds) == 2
        assert scheds[0].get("scheduler") == "fifo"
        assert scheds[0].get("priority") == "5"

    def test_emulatorpin(self):
        ep = self.root.find("cputune/emulatorpin")
        assert ep.get("cpuset") == "0,1"

    def test_vcpu_count_from_cpuset(self):
        assert self.root.findtext("vcpu") == "2"


class TestHugepages:
    def setup_method(self):
        self.root = _parse(
            generate_xml(
                {
                    "name": "hpvm",
                    "hugepages": True,
                    "vcpus": 2,
                }
            )
        )

    def test_memory_gib(self):
        assert self.root.find("memory").get("unit") == "GiB"
        assert self.root.findtext("memory") == "1"

    def test_memory_backing(self):
        mb = self.root.find("memoryBacking")
        assert mb is not None
        assert mb.find("hugepages/page") is not None
        assert mb.find("nosharepages") is not None

    def test_numa_cell(self):
        cell = self.root.find("cpu/numa/cell")
        assert cell is not None
        assert cell.get("cpus") == "0-1"
        assert cell.get("memAccess") == "shared"


class TestBalloon:
    def test_virtio_balloon(self):
        root = _parse(generate_xml({"name": "vm", "balloon": True}))
        mb = root.find("devices/memballoon")
        assert mb.get("model") == "virtio"
        assert mb.find("stats").get("period") == "5"


class TestVnc:
    def setup_method(self):
        self.root = _parse(generate_xml({"name": "vm", "vnc": True}))

    def test_graphics(self):
        gfx = self.root.find("devices/graphics")
        assert gfx.get("type") == "vnc"
        assert gfx.get("autoport") == "yes"

    def test_video(self):
        video = self.root.find("devices/video/model")
        assert video.get("type") == "virtio"

    def test_tablet_input(self):
        inp = self.root.find("devices/input")
        assert inp.get("type") == "tablet"
        assert inp.get("bus") == "usb"

    def test_custom_listen(self):
        root = _parse(
            generate_xml({"name": "vm", "vnc": True, "vnc_listen": "0.0.0.0"})
        )
        gfx = root.find("devices/graphics")
        assert gfx.get("listen") == "0.0.0.0"


class TestSecureBoot:
    def test_secure_boot_enabled(self):
        root = _parse(generate_xml({"name": "vm", "secure_boot": True}))
        feat = root.find("os/firmware/feature")
        assert feat.get("name") == "secure-boot"
        assert feat.get("enabled") == "yes"


class TestNetworkBridge:
    def test_bridge_interface(self):
        root = _parse(
            generate_xml(
                {
                    "name": "vm",
                    "net": ["type=bridge,source=br0," "mac=52:54:00:00:00:01"],
                }
            )
        )
        iface = root.find("devices/interface[@type='bridge']")
        assert iface is not None
        assert iface.find("source").get("bridge") == "br0"
        assert iface.find("mac").get("address") == "52:54:00:00:00:01"
        assert iface.find("model").get("type") == "virtio"

    def test_bridge_with_vlan(self):
        root = _parse(
            generate_xml(
                {
                    "name": "vm",
                    "net": [
                        "type=bridge,source=br0,"
                        "mac=52:54:00:00:00:01,vlan=100"
                    ],
                }
            )
        )
        tag = root.find("devices/interface/vlan/tag")
        assert tag.get("id") == "100"

    def test_bridge_with_virtualport(self):
        root = _parse(
            generate_xml(
                {
                    "name": "vm",
                    "net": [
                        "type=bridge,source=br0,"
                        "mac=52:54:00:00:00:01,"
                        "virtualport=openvswitch"
                    ],
                }
            )
        )
        vp = root.find("devices/interface/virtualport")
        assert vp.get("type") == "openvswitch"


class TestNetworkMacvtap:
    def test_macvtap_interface(self):
        root = _parse(
            generate_xml(
                {
                    "name": "vm",
                    "net": [
                        "type=macvtap,source=eth0,"
                        "mac=52:54:00:00:00:02,mode=bridge"
                    ],
                }
            )
        )
        iface = root.find("devices/interface[@type='direct']")
        assert iface is not None
        assert iface.find("source").get("dev") == "eth0"
        assert iface.find("source").get("mode") == "bridge"

    def test_macvtap_trust_guest_rx(self):
        root = _parse(
            generate_xml(
                {
                    "name": "vm",
                    "net": [
                        "type=macvtap,source=eth0,"
                        "mac=52:54:00:00:00:02,"
                        "trust_guest_rx=yes"
                    ],
                }
            )
        )
        iface = root.find("devices/interface[@type='direct']")
        assert iface.get("trustGuestRxFilters") == "yes"


class TestNetworkPci:
    def test_pci_passthrough(self):
        root = _parse(
            generate_xml(
                {
                    "name": "vm",
                    "net": ["type=pci,address=0000:03:00.0"],
                }
            )
        )
        hostdev = root.find("devices/hostdev[@type='pci']")
        assert hostdev is not None
        addr = hostdev.find("source/address")
        assert addr.get("domain") == "0x0000"
        assert addr.get("bus") == "0x03"
        assert addr.get("slot") == "0x00"
        assert addr.get("function") == "0x0"


class TestNetworkSriov:
    def test_sriov_interface(self):
        root = _parse(
            generate_xml(
                {
                    "name": "vm",
                    "net": ["type=sriov,network=sriov-net"],
                }
            )
        )
        iface = root.find("devices/interface[@type='network']")
        assert iface.find("source").get("network") == "sriov-net"


class TestNetworkOvs:
    def test_ovs_interface(self):
        root = _parse(
            generate_xml(
                {
                    "name": "vm",
                    "net": ["type=ovs,mac=52:54:00:00:00:03," "port=vnet0"],
                }
            )
        )
        iface = root.find("devices/interface[@type='ethernet']")
        assert iface is not None
        assert iface.find("mac").get("address") == "52:54:00:00:00:03"
        assert iface.find("target").get("dev") == "vnet0"


class TestNetworkMultiple:
    def test_mixed_interfaces(self):
        root = _parse(
            generate_xml(
                {
                    "name": "vm",
                    "net": [
                        "type=bridge,source=br0," "mac=52:54:00:00:00:01",
                        "type=sriov,network=sriov-net",
                    ],
                }
            )
        )
        ifaces = root.findall("devices/interface")
        hostdevs = root.findall("devices/hostdev")
        assert len(ifaces) + len(hostdevs) == 2


class TestParseNetArgValid:
    def test_bridge(self):
        d = _parse_net_arg("type=bridge,source=br0,mac=52:54:00:00:00:01")
        assert d["type"] == "bridge"
        assert d["source"] == "br0"

    def test_macvtap(self):
        d = _parse_net_arg("type=macvtap,source=eth0,mac=52:54:00:00:00:01")
        assert d["type"] == "macvtap"

    def test_pci(self):
        d = _parse_net_arg("type=pci,address=0000:03:00.0")
        assert d["address"] == "0000:03:00.0"

    def test_sriov(self):
        d = _parse_net_arg("type=sriov,network=sriov-net")
        assert d["network"] == "sriov-net"

    def test_ovs(self):
        d = _parse_net_arg("type=ovs,mac=52:54:00:00:00:01,port=vnet0")
        assert d["port"] == "vnet0"


class TestParseNetArgInvalid:
    def test_missing_type(self):
        with pytest.raises(ValueError, match="Missing 'type'"):
            _parse_net_arg("source=br0,mac=52:54:00:00:00:01")

    def test_unknown_type(self):
        with pytest.raises(ValueError, match="Unknown network type"):
            _parse_net_arg("type=foobar,source=br0")

    def test_missing_required_key(self):
        with pytest.raises(ValueError, match="Missing required key"):
            _parse_net_arg("type=bridge,source=br0")

    def test_bad_format(self):
        with pytest.raises(ValueError, match="expected key=value"):
            _parse_net_arg("type=bridge,noseparator")
