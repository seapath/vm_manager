# Copyright (C) 2026, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""
Unit tests for the cluster backend, with no cluster.

Every Ceph, Pacemaker and libvirt access is replaced here: RbdManager is
swapped for the recording fake below, Pacemaker for a stub host
validator, and the module functions the code under test delegates to
(_create_vm_group, _configure_vm, remove) for recorders. A failure in
this file therefore points at the function under test and nowhere else.

The fake models the calls, not Ceph itself, with one exception: a copy
carries the source metadata over, because the code under test relies on
that to know what it has to strip from the clone. The fake exposes only
the methods the code is expected to call, so an unexpected one fails with
an AttributeError instead of quietly returning a Mock.

The end-to-end tests that drive a real Ceph and Pacemaker cluster live in
test_vm_manager_cluster.py, which CI ignores.
"""

import datetime
import json
import os

import pytest

import vm_manager
from vm_manager import vm_manager_cluster as vmc
from vm_manager.exceptions import UuidConflictError

pytestmark = pytest.mark.skipif(
    not vm_manager.cluster_mode,
    reason="the cluster backend is only importable in cluster mode",
)

SRC = "srcvm"
DST = "dstvm"
SRC_DISK = vmc.OS_DISK_PREFIX + SRC
DST_DISK = vmc.OS_DISK_PREFIX + DST

# Captured before any fixture replaces them, so the tests that exercise
# them for real can put them back.
REAL_CONFIGURE_VM = vmc._configure_vm
REAL_ENABLE_VM = vmc.enable_vm
REAL_REMOVE = vmc.remove

BASE_XML = (
    "<domain type='kvm'>"
    "<uuid>11111111-2222-3333-4444-555555555555</uuid>"
    "<name>srcvm</name>"
    "</domain>"
)

# What libvirt returns for the source VM of an add_to_cluster: one local
# disk, which the cluster backend has to replace by the Ceph RBD one.
LIBVIRT_XML = (
    "<domain type='kvm'>"
    "<uuid>99999999-8888-7777-6666-555555555555</uuid>"
    "<name>srcvm</name>"
    "<devices>"
    "<disk type='file' device='disk'>"
    "<source file='/var/lib/libvirt/images/srcvm.qcow2'/>"
    "</disk>"
    "</devices>"
    "</domain>"
)


class FakeRbd:
    """Recording stand-in for RbdManager, usable as a context manager."""

    def __init__(self, images=(), metadata=None, groups=None):
        self.images = set(images)
        self.metadata = {
            disk: dict(values) for disk, values in (metadata or {}).items()
        }
        self.groups = {
            name: set(members) for name, members in (groups or {}).items()
        }
        # Image names a copy must not create, to simulate a copy that
        # reports success but leaves nothing behind.
        self.no_create = set()
        # Image names whose group membership cannot be read, to simulate
        # Ceph failing during a rollback.
        self.group_errors = set()
        # Names a removal must not remove, to simulate Ceph objects that
        # survive the call that was supposed to delete them.
        self.undeletable_groups = set()
        self.undeletable_images = set()
        # Image name -> list of {"id", "name", "timestamp"}
        self.snapshots = {}
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    @property
    def call_names(self):
        return [call[0] for call in self.calls]

    def _record(self, name, *args):
        self.calls.append((name,) + args)

    def get_image_metadata(self, disk, key):
        self._record("get_image_metadata", disk, key)
        return self.metadata[disk][key]

    def set_image_metadata(self, disk, key, value):
        self._record("set_image_metadata", disk, key, value)
        self.metadata.setdefault(disk, {})[key] = value

    def remove_image_metadata(self, disk, key):
        self._record("remove_image_metadata", disk, key)
        del self.metadata[disk][key]

    def image_exists(self, name):
        self._record("image_exists", name)
        return name in self.images

    def remove_image(self, name):
        self._record("remove_image", name)
        if name in self.undeletable_images:
            return
        self.images.discard(name)
        self.metadata.pop(name, None)

    def copy_image(self, src, dst, overwrite=False, deep=False):
        self._record("copy_image", src, dst, overwrite, deep)
        if dst in self.no_create:
            return
        self.images.add(dst)
        self.metadata[dst] = dict(self.metadata.get(src, {}))

    def is_image_in_group(self, image, group):
        self._record("is_image_in_group", image, group)
        if image in self.group_errors:
            raise RuntimeError("Ceph is unreachable for " + image)
        return image in self.groups.get(group, set())

    def add_image_to_group(self, image, group):
        self._record("add_image_to_group", image, group)
        self.groups.setdefault(group, set()).add(image)

    def import_qcow2(self, path, name, progress=False):
        self._record("import_qcow2", path, name, progress)
        if name in self.no_create:
            return
        self.images.add(name)
        self.metadata.setdefault(name, {})

    def list_groups(self):
        self._record("list_groups")
        return list(self.groups)

    def group_exists(self, name):
        self._record("group_exists", name)
        return name in self.groups

    def list_group_images(self, name):
        self._record("list_group_images", name)
        return sorted(self.groups[name])

    def remove_group(self, name):
        self._record("remove_group", name)
        if name not in self.undeletable_groups:
            self.groups.pop(name, None)

    def list_image_snapshots(self, disk, flat=True):
        self._record("list_image_snapshots", disk, flat)
        snapshots = self.snapshots.get(disk, [])
        if flat:
            return [snap["name"] for snap in snapshots]
        return [dict(snap) for snap in snapshots]

    def get_image_snapshot_timestamp(self, disk, snap_id):
        self._record("get_image_snapshot_timestamp", disk, snap_id)
        for snap in self.snapshots.get(disk, []):
            if snap["id"] == snap_id:
                return snap["timestamp"]
        raise KeyError(snap_id)

    def remove_image_snapshot(self, disk, name):
        self._record("remove_image_snapshot", disk, name)
        self.snapshots[disk] = [
            snap
            for snap in self.snapshots.get(disk, [])
            if snap["name"] != name
        ]

    def purge_image(self, disk):
        self._record("purge_image", disk)
        self.snapshots[disk] = []


class FakePacemaker:
    """Recording stand-in for Pacemaker, usable as a context manager.

    The cluster resources live on the shared Collaborators rather than on
    the instance, because the code opens a new Pacemaker per operation.
    """

    def __init__(self, collaborators, vm_name):
        self.collaborators = collaborators
        self.vm_name = vm_name
        self.calls = []
        collaborators.pacemakers.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    @property
    def call_names(self):
        return [call[0] for call in self.calls]

    def list_resources(self):
        self.calls.append(("list_resources",))
        return list(self.collaborators.resources)

    def add_vm(self, vm_options, nostart=False):
        self.calls.append(("add_vm", dict(vm_options), nostart))
        if not self.collaborators.add_vm_fails:
            self.collaborators.resources.add(self.vm_name)

    def disable_location(self, host):
        self.calls.append(("disable_location", host))

    def pin_location(self, host):
        self.calls.append(("pin_location", host))

    def default_location(self, host):
        self.calls.append(("default_location", host))

    def run_crm_cmd(self, cmd):
        self.calls.append(("run_crm_cmd", cmd))

    def manage(self):
        self.calls.append(("manage",))

    def wait_for(self, state):
        self.calls.append(("wait_for", state))


class FakeDomain:
    """The subset of a libvirt domain that the cluster backend uses."""

    def __init__(self, xml, active=False):
        self.xml = xml
        self.active = active
        self.destroyed = False

    def XMLDesc(self, flags):
        return self.xml

    def isActive(self):
        return self.active

    def destroy(self):
        self.destroyed = True
        self.active = False


class FakeLibvirt:
    """Recording stand-in for LibVirtManager, usable as a context manager."""

    class _Conn:
        def __init__(self, manager):
            self._manager = manager

        def lookupByName(self, name):
            self._manager.calls.append(("lookupByName", name))
            return self._manager.domains[name]

    def __init__(self, domains=None):
        self.domains = dict(domains or {})
        self.calls = []
        self._conn = self._Conn(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def list(self):
        self.calls.append(("list",))
        return list(self.domains)

    def define(self, xml):
        self.calls.append(("define", xml))

    def undefine(self, name):
        self.calls.append(("undefine", name))
        self.domains.pop(name, None)


class Collaborators:
    """The recorders standing in for what the functions delegate to."""

    def __init__(self, rbd, libvirt, ceph_conf):
        self.rbd = rbd
        self.libvirt = libvirt
        self.ceph_conf = ceph_conf
        self.valid_hosts = {"hyp1", "hyp2"}
        self.configured = []
        self.removed = []
        self.groups_created = []
        self.built_xml = []
        self.built_xml_results = []
        self.uuid_checks = []
        self.configure_error = None
        self.uuid_error = None
        # Pacemaker side
        self.pacemakers = []
        self.resources = set()
        self.add_vm_fails = False
        self.observer = None
        self.remote_nodes = []
        self.enabled = []
        self.disabled = []

    @property
    def pacemaker(self):
        """The single Pacemaker the operation opened."""
        assert (
            len(self.pacemakers) == 1
        ), "expected one Pacemaker, got {}".format(len(self.pacemakers))
        return self.pacemakers[0]

    @property
    def built_xml_result(self):
        """The XML string the last _create_xml() call returned."""
        return self.built_xml_results[-1]

    def configure(self, vm_options):
        # Snapshot, so later mutations cannot rewrite what was asserted.
        self.configured.append(dict(vm_options))
        if self.configure_error is not None:
            raise self.configure_error

    def create_xml(
        self, xml, vm_name, disk_bus="virtio", additional_disks=None
    ):
        self.built_xml.append((xml, vm_name, disk_bus, additional_disks))
        built = "<domain type='kvm'><name>{}</name></domain>".format(vm_name)
        self.built_xml_results.append(built)
        return built

    def check_uuid(self, xml, uuid_source):
        self.uuid_checks.append(xml)
        if self.uuid_error is not None:
            raise self.uuid_error


@pytest.fixture
def rbd():
    """A source VM present in Ceph, with its system disk in its group."""
    return FakeRbd(
        images={SRC_DISK},
        metadata={SRC_DISK: {"_base_xml": BASE_XML}},
        groups={SRC: {SRC_DISK}},
    )


@pytest.fixture
def libvirt_domains():
    """The libvirt side of the source VM, defined and shut off."""
    return FakeLibvirt({SRC: FakeDomain(LIBVIRT_XML)})


@pytest.fixture
def cluster(monkeypatch, tmp_path, rbd, libvirt_domains):
    """Replace every cluster access made by the code under test."""
    # A real file, so the existence checks run for real rather than
    # against a patched os.path.
    ceph_conf = tmp_path / "ceph.conf"
    ceph_conf.write_text("[global]\n")
    collaborators = Collaborators(rbd, libvirt_domains, str(ceph_conf))

    monkeypatch.setattr(vmc, "CEPH_CONF", str(ceph_conf))
    monkeypatch.setattr(
        vmc, "LibVirtManager", lambda *a, **kw: libvirt_domains
    )
    monkeypatch.setattr(vmc, "_create_xml", collaborators.create_xml)
    monkeypatch.setattr(vmc, "check_uuid_conflict", collaborators.check_uuid)
    monkeypatch.setattr(vmc, "RbdManager", lambda *a, **kw: rbd)

    class PacemakerStub(FakePacemaker):
        """Bound to this test's collaborators, and still a class, because
        the code calls is_valid_host on it without instantiating."""

        def __init__(self, vm_name):
            super().__init__(collaborators, vm_name)

        @staticmethod
        def is_valid_host(host):
            return host in collaborators.valid_hosts

    monkeypatch.setattr(vmc, "Pacemaker", PacemakerStub)
    monkeypatch.setattr(
        vmc,
        "_create_vm_group",
        lambda name, force=False: collaborators.groups_created.append(
            (name, force)
        ),
    )
    monkeypatch.setattr(vmc, "_configure_vm", collaborators.configure)
    monkeypatch.setattr(
        vmc,
        "enable_vm",
        lambda name, nostart=False: collaborators.enabled.append(
            (name, nostart)
        ),
    )
    monkeypatch.setattr(
        vmc, "_get_observer_host", lambda: collaborators.observer
    )
    monkeypatch.setattr(
        vmc, "_get_remote_nodes", lambda: list(collaborators.remote_nodes)
    )
    monkeypatch.setattr(
        vmc, "remove", lambda name: collaborators.removed.append(name)
    )
    monkeypatch.setattr(
        vmc, "disable_vm", lambda name: collaborators.disabled.append(name)
    )
    return collaborators


@pytest.fixture
def real_configure_vm(monkeypatch, cluster):
    """Put the real _configure_vm() back, to test it rather than mock it."""
    monkeypatch.setattr(vmc, "_configure_vm", REAL_CONFIGURE_VM)
    return cluster


@pytest.fixture
def real_enable_vm(monkeypatch, cluster):
    """Put the real enable_vm() back, to test it rather than mock it."""
    monkeypatch.setattr(vmc, "enable_vm", REAL_ENABLE_VM)
    return cluster


@pytest.fixture
def real_remove(monkeypatch, cluster):
    """Put the real remove() back, to test it rather than mock it."""
    monkeypatch.setattr(vmc, "remove", REAL_REMOVE)
    return cluster


def options(**overrides):
    """Build a clone() argument dict, base_xml supplied by the caller."""
    values = {"name": SRC, "dst_name": DST}
    values.update(overrides)
    return values


@pytest.fixture
def created(monkeypatch, cluster):
    """Record what add_to_cluster() hands over to create()."""
    calls = []
    monkeypatch.setattr(
        vmc, "create", lambda vm_options: calls.append(dict(vm_options))
    )
    return calls


@pytest.fixture
def disk_file(tmp_path):
    """Create a real disk image file and return its path."""

    def make(name):
        path = tmp_path / name
        path.write_bytes(b"qcow2")
        return str(path)

    return make


@pytest.fixture
def create_options(disk_file):
    """Build a create() argument dict pointing at a real image file."""
    image = disk_file("system.qcow2")

    def build(**overrides):
        values = {"name": DST, "image": image, "base_xml": BASE_XML}
        values.update(overrides)
        return values

    return build


class TestCloneValidation:
    """The checks clone() makes before touching Ceph."""

    def test_source_and_destination_must_differ(self, cluster):
        vm_options = options(dst_name=SRC)
        with pytest.raises(ValueError, match="same name"):
            vmc.clone(vm_options)
        assert cluster.rbd.calls == []

    @pytest.mark.parametrize("name", ["with space", "with-dash", "", "xml"])
    def test_destination_name_is_validated(self, cluster, name):
        vm_options = options(dst_name=name)
        with pytest.raises(ValueError):
            vmc.clone(vm_options)
        assert cluster.rbd.calls == []

    def test_none_values_are_dropped(self, cluster):
        """A None option must not be seen as supplied."""
        vmc.clone(options(base_xml=BASE_XML, force=None))
        assert cluster.groups_created == [(DST, False)]

    def test_metadata_must_be_a_dictionary(self, cluster):
        vm_options = options(base_xml=BASE_XML, metadata="not-a-dict")
        with pytest.raises(ValueError, match="metadata parameter"):
            vmc.clone(vm_options)

    def test_metadata_keys_are_validated(self, cluster):
        vm_options = options(base_xml=BASE_XML, metadata={"bad key": "value"})
        with pytest.raises(ValueError):
            vmc.clone(vm_options)

    def test_valid_metadata_is_accepted(self, cluster):
        vmc.clone(options(base_xml=BASE_XML, metadata={"owner": "team1"}))
        assert cluster.configured[0]["metadata"] == {"owner": "team1"}

    def test_valid_pacemaker_options_are_accepted(self, cluster):
        vmc.clone(
            options(
                base_xml=BASE_XML,
                pacemaker_meta={"priority": "10"},
                pacemaker_params={"timeout": "30"},
                pacemaker_utilization={"cpu": "2"},
            )
        )
        assert cluster.configured[0]["pacemaker_utilization"] == {"cpu": "2"}

    @pytest.mark.parametrize(
        "option",
        ["pacemaker_meta", "pacemaker_params", "pacemaker_utilization"],
    )
    def test_pacemaker_options_must_be_dictionaries(self, cluster, option):
        vm_options = options(base_xml=BASE_XML, **{option: "not-a-dict"})
        with pytest.raises(ValueError, match=option):
            vmc.clone(vm_options)


class TestCloneSourceXml:
    """Where the libvirt XML of the clone comes from."""

    def test_base_xml_is_read_from_the_source(self, cluster):
        vmc.clone(options())
        assert (
            "get_image_metadata",
            SRC_DISK,
            "_base_xml",
        ) in cluster.rbd.calls

    def test_missing_base_xml_metadata_is_fatal(self, cluster):
        del cluster.rbd.metadata[SRC_DISK]["_base_xml"]
        vm_options = options()
        with pytest.raises(KeyError):
            vmc.clone(vm_options)
        assert cluster.configured == []

    def test_supplied_base_xml_is_not_read_from_the_source(self, cluster):
        vmc.clone(options(base_xml=BASE_XML))
        assert (
            "get_image_metadata",
            SRC_DISK,
            "_base_xml",
        ) not in cluster.rbd.calls

    def test_source_uuid_is_stripped(self, cluster):
        """The clone must get a fresh UUID, not the one of its source."""
        vmc.clone(options(base_xml=BASE_XML))
        assert "<uuid>" not in cluster.configured[0]["base_xml"]

    def test_configured_under_the_destination_name(self, cluster):
        vmc.clone(options(base_xml=BASE_XML))
        assert cluster.configured[0]["name"] == DST


class TestCloneHosts:
    """Inheritance and validation of the placement constraints."""

    def test_preferred_host_is_inherited(self, cluster):
        cluster.rbd.metadata[SRC_DISK]["_preferred_host"] = "hyp1"
        vmc.clone(options(base_xml=BASE_XML))
        assert cluster.configured[0]["preferred_host"] == "hyp1"

    def test_pinned_host_is_inherited(self, cluster):
        cluster.rbd.metadata[SRC_DISK]["_pinned_host"] = "hyp2"
        vmc.clone(options(base_xml=BASE_XML))
        assert cluster.configured[0]["pinned_host"] == "hyp2"

    def test_source_without_host_metadata_is_tolerated(self, cluster):
        vmc.clone(options(base_xml=BASE_XML))
        configured = cluster.configured[0]
        assert "preferred_host" not in configured
        assert "pinned_host" not in configured

    def test_clear_constraint_skips_inheritance(self, cluster):
        cluster.rbd.metadata[SRC_DISK]["_preferred_host"] = "hyp1"
        vmc.clone(options(base_xml=BASE_XML, clear_constraint=True))
        assert "preferred_host" not in cluster.configured[0]

    def test_explicit_host_skips_inheritance(self, cluster):
        cluster.rbd.metadata[SRC_DISK]["_preferred_host"] = "hyp1"
        vmc.clone(options(base_xml=BASE_XML, pinned_host="hyp2"))
        configured = cluster.configured[0]
        assert configured["pinned_host"] == "hyp2"
        assert "preferred_host" not in configured

    def test_invalid_pinned_host_is_rejected(self, cluster):
        vm_options = options(base_xml=BASE_XML, pinned_host="nowhere")
        with pytest.raises(ValueError, match="not valid hypervisor"):
            vmc.clone(vm_options)

    def test_invalid_preferred_host_is_rejected(self, cluster):
        vm_options = options(base_xml=BASE_XML, preferred_host="nowhere")
        with pytest.raises(ValueError, match="not valid hypervisor"):
            vmc.clone(vm_options)


class TestClonePacemakerOptions:
    """How the crm settings of the source reach the clone."""

    def test_inherited_and_merged_with_the_new_values(self, cluster):
        cluster.rbd.metadata[SRC_DISK]["_pacemaker_meta"] = json.dumps(
            {"kept": "1", "overridden": "old"}
        )
        vmc.clone(
            options(
                base_xml=BASE_XML,
                pacemaker_meta={"overridden": "new", "added": "2"},
            )
        )
        assert cluster.configured[0]["pacemaker_meta"] == {
            "kept": "1",
            "overridden": "new",
            "added": "2",
        }

    def test_absent_on_the_source_keeps_the_new_values(self, cluster):
        vmc.clone(options(base_xml=BASE_XML, pacemaker_params={"only": "new"}))
        assert cluster.configured[0]["pacemaker_params"] == {"only": "new"}

    def test_non_dict_metadata_on_the_source_is_rejected(self, cluster):
        cluster.rbd.metadata[SRC_DISK]["_pacemaker_meta"] = json.dumps(
            ["not", "a", "dict"]
        )
        vm_options = options(base_xml=BASE_XML)
        with pytest.raises(ValueError, match="must be a dictionary"):
            vmc.clone(vm_options)

    def test_clear_skips_inheritance(self, cluster):
        cluster.rbd.metadata[SRC_DISK]["_pacemaker_meta"] = json.dumps(
            {"inherited": "1"}
        )
        vmc.clone(options(base_xml=BASE_XML, clear_pacemaker_meta=True))
        assert (
            "get_image_metadata",
            SRC_DISK,
            "_pacemaker_meta",
        ) not in cluster.rbd.calls

    def test_written_on_the_clone_when_not_empty(self, cluster):
        vmc.clone(options(base_xml=BASE_XML, pacemaker_meta={"a": "1"}))
        assert (
            "set_image_metadata",
            DST_DISK,
            "_pacemaker_meta",
            json.dumps({"a": "1"}),
        ) in cluster.rbd.calls


class TestCloneDisks:
    """The Ceph image copies."""

    def test_group_is_created_for_the_destination(self, cluster):
        vmc.clone(options(base_xml=BASE_XML, force=True))
        assert cluster.groups_created == [(DST, True)]

    def test_system_disk_is_deep_copied(self, cluster):
        vmc.clone(options(base_xml=BASE_XML))
        assert (
            "copy_image",
            SRC_DISK,
            DST_DISK,
            False,
            True,
        ) in cluster.rbd.calls

    def test_force_is_passed_to_the_copy(self, cluster):
        vmc.clone(options(base_xml=BASE_XML, force=True))
        assert (
            "copy_image",
            SRC_DISK,
            DST_DISK,
            True,
            True,
        ) in cluster.rbd.calls

    def test_existing_destination_image_is_removed_first(self, cluster):
        cluster.rbd.images.add(DST_DISK)
        vmc.clone(options(base_xml=BASE_XML))
        calls = cluster.rbd.call_names
        assert calls.index("remove_image") < calls.index("copy_image")

    def test_additional_disks_are_cloned(self, cluster):
        cluster.rbd.metadata[SRC_DISK]["_additional_disks"] = json.dumps(2)
        vmc.clone(options(base_xml=BASE_XML))
        for index in range(2):
            assert (
                "copy_image",
                vmc._additional_disk_name(index, SRC),
                vmc._additional_disk_name(index, DST),
                False,
                True,
            ) in cluster.rbd.calls

    def test_additional_disk_count_is_passed_on(self, cluster):
        cluster.rbd.metadata[SRC_DISK]["_additional_disks"] = json.dumps(2)
        vmc.clone(options(base_xml=BASE_XML))
        assert cluster.configured[0]["_known_additional_count"] == 2

    def test_no_additional_disk_leaves_the_count_unset(self, cluster):
        vmc.clone(options(base_xml=BASE_XML))
        assert "_known_additional_count" not in cluster.configured[0]

    def test_existing_additional_disk_is_removed_first(self, cluster):
        cluster.rbd.metadata[SRC_DISK]["_additional_disks"] = json.dumps(1)
        cluster.rbd.images.add(vmc._additional_disk_name(0, DST))
        vmc.clone(options(base_xml=BASE_XML))
        assert (
            "remove_image",
            vmc._additional_disk_name(0, DST),
        ) in cluster.rbd.calls

    def test_additional_disk_copy_failure_is_reported(self, cluster):
        cluster.rbd.metadata[SRC_DISK]["_additional_disks"] = json.dumps(1)
        cluster.rbd.no_create.add(vmc._additional_disk_name(0, DST))
        vm_options = options(base_xml=BASE_XML)
        with pytest.raises(RuntimeError, match="Could not clone additional"):
            vmc.clone(vm_options)


class TestCloneDestinationMetadata:
    """What the clone must not keep from its source."""

    @pytest.mark.parametrize(
        "key",
        [
            "_preferred_host",
            "_pinned_host",
            "_pacemaker_meta",
            "_pacemaker_params",
            "_pacemaker_utilization",
        ],
    )
    def test_source_placement_metadata_is_stripped(self, cluster, key):
        cluster.rbd.metadata[SRC_DISK][key] = json.dumps({"host": "hyp1"})
        cluster.valid_hosts.add(json.dumps({"host": "hyp1"}))
        vmc.clone(options(base_xml=BASE_XML))
        assert ("remove_image_metadata", DST_DISK, key) in cluster.rbd.calls

    def test_absent_metadata_is_tolerated(self, cluster):
        vmc.clone(options(base_xml=BASE_XML))
        assert cluster.configured, "clone() gave up on a clean source"

    def test_disk_bus_is_inherited(self, cluster):
        cluster.rbd.metadata[SRC_DISK]["_disk_bus"] = "sata"
        vmc.clone(options(base_xml=BASE_XML))
        assert cluster.configured[0]["disk_bus"] == "sata"

    def test_disk_bus_defaults_to_virtio(self, cluster):
        vmc.clone(options(base_xml=BASE_XML))
        assert cluster.configured[0]["disk_bus"] == "virtio"


class TestCloneRollback:
    """What happens when the clone fails halfway."""

    def test_failed_configuration_removes_the_clone(self, cluster):
        cluster.configure_error = RuntimeError("boom")
        vm_options = options(base_xml=BASE_XML)
        with pytest.raises(RuntimeError, match="boom"):
            vmc.clone(vm_options)
        assert cluster.removed == [DST]

    def test_source_disk_is_put_back_in_its_group(self, cluster):
        cluster.rbd.groups[SRC] = set()
        cluster.configure_error = RuntimeError("boom")
        vm_options = options(base_xml=BASE_XML)
        with pytest.raises(RuntimeError):
            vmc.clone(vm_options)
        assert SRC_DISK in cluster.rbd.groups[SRC]

    def test_source_disk_already_grouped_is_left_alone(self, cluster):
        cluster.configure_error = RuntimeError("boom")
        vm_options = options(base_xml=BASE_XML)
        with pytest.raises(RuntimeError):
            vmc.clone(vm_options)
        assert (
            "add_image_to_group",
            SRC_DISK,
            SRC,
        ) not in cluster.rbd.calls

    def test_source_additional_disks_are_put_back(self, cluster):
        cluster.rbd.metadata[SRC_DISK]["_additional_disks"] = json.dumps(1)
        cluster.configure_error = RuntimeError("boom")
        vm_options = options(base_xml=BASE_XML)
        with pytest.raises(RuntimeError):
            vmc.clone(vm_options)
        assert vmc._additional_disk_name(0, SRC) in cluster.rbd.groups[SRC]

    def test_source_additional_disks_already_grouped_are_left_alone(
        self, cluster
    ):
        cluster.rbd.metadata[SRC_DISK]["_additional_disks"] = json.dumps(2)
        for index in range(2):
            cluster.rbd.groups[SRC].add(vmc._additional_disk_name(index, SRC))
        cluster.configure_error = RuntimeError("boom")
        vm_options = options(base_xml=BASE_XML)
        with pytest.raises(RuntimeError):
            vmc.clone(vm_options)
        assert (
            "add_image_to_group",
            vmc._additional_disk_name(0, SRC),
            SRC,
        ) not in cluster.rbd.calls

    def test_rollback_survives_ceph_failing_on_additional_disks(self, cluster):
        """A rollback that cannot regroup a disk still reports the cause."""
        cluster.rbd.metadata[SRC_DISK]["_additional_disks"] = json.dumps(1)
        cluster.rbd.group_errors.add(vmc._additional_disk_name(0, SRC))
        cluster.configure_error = RuntimeError("boom")
        vm_options = options(base_xml=BASE_XML)
        with pytest.raises(RuntimeError, match="boom"):
            vmc.clone(vm_options)

    def test_failed_system_disk_copy_is_reported(self, cluster):
        """The rollback must not hide what made it run.

        It loops over src_additional_count, which the copy above it can
        fail before setting.
        """
        cluster.rbd.no_create.add(DST_DISK)
        vm_options = options(base_xml=BASE_XML)
        with pytest.raises(Exception, match="Could not create image disk"):
            vmc.clone(vm_options)
        assert cluster.removed == [DST]


def test_successful_clone_is_logged(cluster, caplog):
    with caplog.at_level("INFO", logger=vmc.logger.name):
        vmc.clone(options(base_xml=BASE_XML))
    assert "successfully cloned" in caplog.text


class TestCreateValidation:
    """The checks create() makes before importing anything."""

    def test_name_is_validated(self, cluster, create_options):
        vm_options = create_options(name="bad name")
        with pytest.raises(ValueError):
            vmc.create(vm_options)
        assert cluster.rbd.calls == []

    def test_metadata_must_be_a_dictionary(self, cluster, create_options):
        vm_options = create_options(metadata="not-a-dict")
        with pytest.raises(ValueError, match="metadata parameter"):
            vmc.create(vm_options)

    def test_metadata_keys_are_validated(self, cluster, create_options):
        vm_options = create_options(metadata={"bad key": "value"})
        with pytest.raises(ValueError):
            vmc.create(vm_options)

    @pytest.mark.parametrize(
        "option",
        ["pacemaker_meta", "pacemaker_params", "pacemaker_utilization"],
    )
    def test_pacemaker_options_must_be_dictionaries(
        self, cluster, create_options, option
    ):
        vm_options = create_options(
            metadata={"ok": "1"}, **{option: "not-a-dict"}
        )
        with pytest.raises(ValueError, match=option):
            vmc.create(vm_options)

    @pytest.mark.parametrize(
        "option",
        ["pacemaker_meta", "pacemaker_params", "pacemaker_utilization"],
    )
    def test_pacemaker_options_are_validated_without_metadata(
        self, cluster, create_options, option
    ):
        """The checks must not depend on metadata being passed too.

        _configure_vm would store the string as JSON, and the next clone
        of that VM would fail on it.
        """
        vm_options = create_options(**{option: "not-a-dict"})
        with pytest.raises(ValueError, match=option):
            vmc.create(vm_options)

    def test_valid_metadata_and_pacemaker_options_are_accepted(
        self, cluster, create_options
    ):
        vmc.create(
            create_options(
                metadata={"owner": "team1"},
                pacemaker_meta={"priority": "10"},
                pacemaker_params={"timeout": "30"},
                pacemaker_utilization={"cpu": "2"},
            )
        )
        assert cluster.configured[0]["metadata"] == {"owner": "team1"}

    def test_missing_ceph_conf_is_reported(
        self, cluster, create_options, monkeypatch
    ):
        monkeypatch.setattr(vmc, "CEPH_CONF", "/nonexistent/ceph.conf")
        vm_options = create_options()
        with pytest.raises(IOError, match="Could not find file"):
            vmc.create(vm_options)

    def test_missing_image_is_reported(self, cluster, create_options):
        vm_options = create_options(image="/nonexistent/system.qcow2")
        with pytest.raises(IOError, match="Could not find file"):
            vmc.create(vm_options)

    def test_missing_additional_disk_is_reported(
        self, cluster, create_options
    ):
        vm_options = create_options(
            additional_disks=["/nonexistent/data.qcow2"]
        )
        with pytest.raises(IOError, match="Could not find file"):
            vmc.create(vm_options)

    def test_invalid_pinned_host_is_rejected(self, cluster, create_options):
        vm_options = create_options(pinned_host="nowhere")
        with pytest.raises(Exception, match="not valid hypervisor"):
            vmc.create(vm_options)

    def test_invalid_preferred_host_is_rejected(self, cluster, create_options):
        vm_options = create_options(preferred_host="nowhere")
        with pytest.raises(Exception, match="not a valid hypervisor"):
            vmc.create(vm_options)

    def test_valid_hosts_are_accepted(self, cluster, create_options):
        vmc.create(create_options(pinned_host="hyp1", preferred_host="hyp2"))
        assert cluster.configured[0]["pinned_host"] == "hyp1"

    def test_uuid_conflict_is_fatal(self, cluster, create_options):
        cluster.uuid_error = UuidConflictError("uuid already used")
        vm_options = create_options()
        with pytest.raises(UuidConflictError):
            vmc.create(vm_options)
        assert cluster.groups_created == []

    def test_uuid_is_checked_on_the_generated_xml(
        self, cluster, create_options
    ):
        vmc.create(create_options())
        assert cluster.uuid_checks == [cluster.built_xml_result]


class TestCreateDisks:
    """The qcow2 imports create() drives."""

    def test_group_is_created(self, cluster, create_options):
        vmc.create(create_options(force=True))
        assert cluster.groups_created == [(DST, True)]

    def test_force_defaults_to_false(self, cluster, create_options):
        vmc.create(create_options())
        assert cluster.groups_created == [(DST, False)]

    def test_existing_image_is_removed_first(self, cluster, create_options):
        cluster.rbd.images.add(DST_DISK)
        vmc.create(create_options())
        calls = cluster.rbd.call_names
        assert calls.index("remove_image") < calls.index("import_qcow2")

    def test_system_disk_is_imported(self, cluster, create_options):
        vm_options = create_options()
        vmc.create(vm_options)
        assert (
            "import_qcow2",
            vm_options["image"],
            DST_DISK,
            False,
        ) in cluster.rbd.calls

    def test_progress_is_forwarded(self, cluster, create_options):
        vm_options = create_options(progress=True)
        vmc.create(vm_options)
        assert (
            "import_qcow2",
            vm_options["image"],
            DST_DISK,
            True,
        ) in cluster.rbd.calls

    def test_failed_import_is_reported(self, cluster, create_options):
        cluster.rbd.no_create.add(DST_DISK)
        vm_options = create_options()
        with pytest.raises(RuntimeError, match="Could not import qcow2"):
            vmc.create(vm_options)

    def test_additional_disks_are_imported(
        self, cluster, create_options, disk_file
    ):
        extra = [disk_file("data0.qcow2"), disk_file("data1.qcow2")]
        vmc.create(create_options(additional_disks=extra))
        for index, path in enumerate(extra):
            assert (
                "import_qcow2",
                path,
                vmc._additional_disk_name(index, DST),
                False,
            ) in cluster.rbd.calls

    def test_existing_additional_image_is_removed_first(
        self, cluster, create_options, disk_file
    ):
        cluster.rbd.images.add(vmc._additional_disk_name(0, DST))
        vmc.create(create_options(additional_disks=[disk_file("data.qcow2")]))
        assert (
            "remove_image",
            vmc._additional_disk_name(0, DST),
        ) in cluster.rbd.calls

    def test_failed_additional_import_is_reported(
        self, cluster, create_options, disk_file
    ):
        cluster.rbd.no_create.add(vmc._additional_disk_name(0, DST))
        vm_options = create_options(additional_disks=[disk_file("data.qcow2")])
        with pytest.raises(RuntimeError, match="Could not import qcow2"):
            vmc.create(vm_options)


class TestCreateConfiguration:
    """What create() hands over to _configure_vm()."""

    def test_disk_name_is_passed_on(self, cluster, create_options):
        vmc.create(create_options())
        assert cluster.configured[0]["disk_name"] == DST_DISK

    def test_disk_bus_defaults_to_virtio(self, cluster, create_options):
        vmc.create(create_options())
        assert cluster.configured[0]["disk_bus"] == "virtio"

    def test_explicit_disk_bus_is_kept(self, cluster, create_options):
        vmc.create(create_options(disk_bus="sata"))
        assert cluster.configured[0]["disk_bus"] == "sata"
        assert cluster.built_xml[0][2] == "sata"

    def test_none_values_are_dropped(self, cluster, create_options):
        vmc.create(create_options(force=None, metadata=None))
        assert cluster.groups_created == [(DST, False)]

    def test_failed_configuration_removes_the_vm(
        self, cluster, create_options
    ):
        cluster.configure_error = RuntimeError("boom")
        vm_options = create_options()
        with pytest.raises(RuntimeError, match="boom"):
            vmc.create(vm_options)
        assert cluster.removed == [DST]

    def test_success_is_logged(self, cluster, create_options, caplog):
        with caplog.at_level("INFO", logger=vmc.logger.name):
            vmc.create(create_options())
        assert "created successfully" in caplog.text


class TestAddToCluster:
    """add_to_cluster(): what it reads from libvirt and hands to create()."""

    def test_target_name_is_validated(self, cluster, created):
        with pytest.raises(ValueError):
            vmc.add_to_cluster({"name": SRC, "new_name": "bad name"})
        assert created == []

    def test_unknown_source_is_rejected(self, cluster, created):
        with pytest.raises(Exception, match="does not exist in libvirt"):
            vmc.add_to_cluster({"name": "ghostvm"})

    def test_several_disks_are_rejected(self, cluster, created):
        cluster.libvirt.domains[SRC] = FakeDomain(
            LIBVIRT_XML.replace(
                "</devices>",
                "<disk type='file' device='disk'>"
                "<source file='/tmp/second.qcow2'/>"
                "</disk></devices>",
            )
        )
        with pytest.raises(Exception, match="more than one disk"):
            vmc.add_to_cluster({"name": SRC})

    def test_image_comes_from_the_disk_source_file(self, cluster, created):
        vmc.add_to_cluster({"name": SRC})
        assert created[0]["image"] == "/var/lib/libvirt/images/srcvm.qcow2"

    def test_image_comes_from_the_disk_source_dev(self, cluster, created):
        cluster.libvirt.domains[SRC] = FakeDomain(
            LIBVIRT_XML.replace(
                "<source file='/var/lib/libvirt/images/srcvm.qcow2'/>",
                "<source dev='/dev/sdb'/>",
            )
        )
        vmc.add_to_cluster({"name": SRC})
        assert created[0]["image"] == "/dev/sdb"

    def test_explicit_image_wins(self, cluster, created):
        vmc.add_to_cluster({"name": SRC, "image": "/somewhere/else.qcow2"})
        assert created[0]["image"] == "/somewhere/else.qcow2"

    def test_disk_without_source_is_reported(self, cluster, created):
        cluster.libvirt.domains[SRC] = FakeDomain(
            LIBVIRT_XML.replace(
                "<source file='/var/lib/libvirt/images/srcvm.qcow2'/>", ""
            )
        )
        with pytest.raises(Exception, match="Could not determine disk image"):
            vmc.add_to_cluster({"name": SRC})

    def test_source_without_path_is_reported(self, cluster, created):
        cluster.libvirt.domains[SRC] = FakeDomain(
            LIBVIRT_XML.replace(
                "<source file='/var/lib/libvirt/images/srcvm.qcow2'/>",
                "<source/>",
            )
        )
        with pytest.raises(Exception, match="Could not determine disk image"):
            vmc.add_to_cluster({"name": SRC})

    def test_domain_without_devices_is_reported(self, cluster, created):
        cluster.libvirt.domains[SRC] = FakeDomain(
            "<domain type='kvm'><name>srcvm</name></domain>"
        )
        with pytest.raises(Exception, match="Could not determine disk image"):
            vmc.add_to_cluster({"name": SRC})

    def test_domain_without_devices_accepts_an_explicit_image(
        self, cluster, created
    ):
        cluster.libvirt.domains[SRC] = FakeDomain(
            "<domain type='kvm'><name>srcvm</name></domain>"
        )
        vmc.add_to_cluster({"name": SRC, "image": "/somewhere/else.qcow2"})
        assert created[0]["image"] == "/somewhere/else.qcow2"

    def test_local_disk_is_stripped_from_the_xml(self, cluster, created):
        vmc.add_to_cluster({"name": SRC})
        assert "<disk" not in created[0]["base_xml"]

    def test_rename_strips_the_uuid(self, cluster, created):
        vmc.add_to_cluster({"name": SRC, "new_name": "othervm"})
        assert "<uuid>" not in created[0]["base_xml"]
        assert created[0]["name"] == "othervm"

    def test_rename_of_a_domain_without_uuid_is_fine(self, cluster, created):
        cluster.libvirt.domains[SRC] = FakeDomain(
            LIBVIRT_XML.replace(
                "<uuid>99999999-8888-7777-6666-555555555555</uuid>", ""
            )
        )
        vmc.add_to_cluster({"name": SRC, "new_name": "othervm"})
        assert created[0]["name"] == "othervm"

    def test_rename_leaves_the_source_defined(self, cluster, created):
        vmc.add_to_cluster({"name": SRC, "new_name": "othervm"})
        assert ("undefine", SRC) not in cluster.libvirt.calls

    def test_same_name_keeps_the_uuid(self, cluster, created):
        vmc.add_to_cluster({"name": SRC})
        assert "<uuid>" in created[0]["base_xml"]

    def test_same_name_undefines_the_source(self, cluster, created):
        vmc.add_to_cluster({"name": SRC})
        assert ("undefine", SRC) in cluster.libvirt.calls

    def test_running_source_is_destroyed_first(self, cluster, created):
        domain = FakeDomain(LIBVIRT_XML, active=True)
        cluster.libvirt.domains[SRC] = domain
        vmc.add_to_cluster({"name": SRC})
        assert domain.destroyed

    def test_stopped_source_is_not_destroyed(self, cluster, created):
        domain = cluster.libvirt.domains[SRC]
        vmc.add_to_cluster({"name": SRC})
        assert not domain.destroyed

    def test_none_values_are_dropped(self, cluster, created):
        vmc.add_to_cluster({"name": SRC, "new_name": None})
        assert created[0]["name"] == SRC

    def test_create_options_are_forwarded(self, cluster, created):
        vmc.add_to_cluster({"name": SRC, "force": True, "disable": True})
        assert created[0]["force"] is True
        assert created[0]["disable"] is True

    def test_import_is_logged(self, cluster, created, caplog):
        with caplog.at_level("INFO", logger=vmc.logger.name):
            vmc.add_to_cluster({"name": SRC, "new_name": "othervm"})
        assert "imported as othervm" in caplog.text


def configure_options(**overrides):
    """Build a _configure_vm() argument dict."""
    values = {"name": DST, "base_xml": BASE_XML, "disk_bus": "virtio"}
    values.update(overrides)
    return values


class TestConfigureVmDisks:
    """_configure_vm(): the group and the disk count."""

    def test_system_disk_joins_the_group(self, real_configure_vm):
        vmc._configure_vm(configure_options())
        assert (
            "add_image_to_group",
            DST_DISK,
            DST,
        ) in real_configure_vm.rbd.calls

    def test_additional_disks_join_the_group(self, real_configure_vm):
        vmc._configure_vm(
            configure_options(additional_disks=["/a.qcow2", "/b.qcow2"])
        )
        for index in range(2):
            assert (
                "add_image_to_group",
                vmc._additional_disk_name(index, DST),
                DST,
            ) in real_configure_vm.rbd.calls

    def test_known_count_wins_over_the_disk_list(self, real_configure_vm):
        """A clone passes the count it read from the source, not paths."""
        vmc._configure_vm(configure_options(_known_additional_count=3))
        assert (
            "set_image_metadata",
            DST_DISK,
            "_additional_disks",
            json.dumps(3),
        ) in real_configure_vm.rbd.calls

    def test_disk_count_is_not_stored_without_additional_disks(
        self, real_configure_vm
    ):
        vmc._configure_vm(configure_options())
        assert (
            "_additional_disks" not in real_configure_vm.rbd.metadata[DST_DISK]
        )

    def test_additional_disks_reach_the_xml_builder(self, real_configure_vm):
        vmc._configure_vm(configure_options(_known_additional_count=1))
        assert real_configure_vm.built_xml[0][3] == [
            vmc._additional_disk_name(0, DST)
        ]

    def test_no_additional_disk_passes_none_to_the_xml_builder(
        self, real_configure_vm
    ):
        vmc._configure_vm(configure_options())
        assert real_configure_vm.built_xml[0][3] is None


class TestConfigureVmMetadata:
    """_configure_vm(): what it writes on the system disk."""

    def _metadata(self, cluster, **overrides):
        vmc._configure_vm(configure_options(**overrides))
        return cluster.rbd.metadata[DST_DISK]

    def test_name_and_xml_are_stored(self, real_configure_vm):
        stored = self._metadata(real_configure_vm)
        assert stored["vm_name"] == DST
        assert stored["_base_xml"] == BASE_XML
        assert stored["xml"] == real_configure_vm.built_xml_result

    def test_live_migration_is_stored_when_asked(self, real_configure_vm):
        stored = self._metadata(real_configure_vm, live_migration=True)
        assert stored["_live_migration"] == "true"

    def test_live_migration_is_not_stored_otherwise(self, real_configure_vm):
        assert "_live_migration" not in self._metadata(real_configure_vm)

    @pytest.mark.parametrize(
        "option,key",
        [
            ("migration_user", "_migration_user"),
            ("stop_timeout", "_stop_timeout"),
            ("migrate_to_timeout", "_migrate_to_timeout"),
            ("migration_downtime", "_migration_downtime"),
            ("priority", "_priority"),
        ],
    )
    def test_optional_settings_are_stored(
        self, real_configure_vm, option, key
    ):
        stored = self._metadata(real_configure_vm, **{option: "value"})
        assert stored[key] == "value"

    def test_pinned_host_is_stored(self, real_configure_vm):
        stored = self._metadata(real_configure_vm, pinned_host="hyp1")
        assert stored["_pinned_host"] == "hyp1"
        assert "_preferred_host" not in stored

    def test_preferred_host_is_stored(self, real_configure_vm):
        stored = self._metadata(real_configure_vm, preferred_host="hyp2")
        assert stored["_preferred_host"] == "hyp2"

    def test_pinned_host_wins_over_preferred(self, real_configure_vm):
        stored = self._metadata(
            real_configure_vm, pinned_host="hyp1", preferred_host="hyp2"
        )
        assert stored["_pinned_host"] == "hyp1"
        assert "_preferred_host" not in stored

    def test_crm_commands_are_stored_as_one_string(self, real_configure_vm):
        stored = self._metadata(
            real_configure_vm, crm_config_cmd=["cmd one", "cmd two"]
        )
        assert stored["_crm_config_cmd"] == "cmd one\ncmd two"

    def test_user_metadata_is_stored(self, real_configure_vm):
        stored = self._metadata(
            real_configure_vm, metadata={"owner": "team1", "site": "paris"}
        )
        assert stored["owner"] == "team1"
        assert stored["site"] == "paris"

    def test_disk_bus_is_stored(self, real_configure_vm):
        assert self._metadata(real_configure_vm)["_disk_bus"] == "virtio"

    @pytest.mark.parametrize(
        "option",
        ["pacemaker_meta", "pacemaker_params", "pacemaker_utilization"],
    )
    def test_pacemaker_options_are_stored_as_json(
        self, real_configure_vm, option
    ):
        stored = self._metadata(real_configure_vm, **{option: {"a": "1"}})
        assert stored["_" + option] == json.dumps({"a": "1"})


class TestConfigureVmHandover:
    """_configure_vm(): libvirt and Pacemaker."""

    def test_xml_is_defined_then_undefined(self, real_configure_vm):
        vmc._configure_vm(configure_options())
        assert real_configure_vm.libvirt.calls == [
            ("define", real_configure_vm.built_xml_result),
            ("undefine", DST),
        ]

    def test_vm_is_enabled_by_default(self, real_configure_vm):
        vmc._configure_vm(configure_options())
        assert real_configure_vm.enabled == [(DST, False)]

    def test_enable_true_enables_the_vm(self, real_configure_vm):
        vmc._configure_vm(configure_options(enable=True))
        assert real_configure_vm.enabled == [(DST, False)]

    def test_enable_false_leaves_it_disabled(self, real_configure_vm):
        vmc._configure_vm(configure_options(enable=False))
        assert real_configure_vm.enabled == []

    def test_nostart_is_forwarded(self, real_configure_vm):
        vmc._configure_vm(configure_options(nostart=True))
        assert real_configure_vm.enabled == [(DST, True)]


class TestEnableVmMetadata:
    """enable_vm(): the Pacemaker options it reads from Ceph."""

    ALL_METADATA = {
        "_preferred_host": "hyp1",
        "_live_migration": "true",
        "_migration_user": "someuser",
        "_stop_timeout": "45",
        "_migrate_to_timeout": "180",
        "_migration_downtime": "5",
        "_crm_config_cmd": "cmd one\ncmd two",
        "_priority": "10",
        "_remote_node": "remote1",
        "_remote_node_address": "10.0.0.1",
        "_remote_node_port": "3121",
        "_remote_node_timeout": "60",
        "_pacemaker_meta": json.dumps({"meta": "1"}),
        "_pacemaker_params": json.dumps({"param": "2"}),
        "_pacemaker_utilization": json.dumps({"cpu": "2"}),
    }

    def _added(self, cluster, vm_name=DST, nostart=False):
        vmc.enable_vm(vm_name, nostart)
        added = [
            call for call in cluster.pacemaker.calls if call[0] == "add_vm"
        ]
        assert added, "enable_vm() did not add the VM"
        return added[0][1]

    def test_defaults_when_the_disk_has_no_metadata(self, real_enable_vm):
        vm_options = self._added(real_enable_vm)
        assert vm_options["live_migration"] == "false"
        assert vm_options["migration_user"] == "root"
        assert vm_options["stop_timeout"] == "30"
        assert vm_options["migrate_to_timeout"] == "120"
        assert vm_options["migration_downtime"] == "0"
        assert vm_options["priority"] == "0"
        assert vm_options["pacemaker_remote"] is None
        assert vm_options["custom_meta"] == {}
        assert vm_options["custom_params"] == {}
        assert vm_options["custom_utilization"] == {}

    def test_every_setting_is_read_from_the_disk(self, real_enable_vm):
        real_enable_vm.rbd.metadata[DST_DISK] = dict(self.ALL_METADATA)
        vm_options = self._added(real_enable_vm)
        assert vm_options["live_migration"] == "true"
        assert vm_options["migration_user"] == "someuser"
        assert vm_options["stop_timeout"] == "45"
        assert vm_options["migrate_to_timeout"] == "180"
        assert vm_options["migration_downtime"] == "5"
        assert vm_options["priority"] == "10"
        assert vm_options["pacemaker_remote"] == "remote1"
        assert vm_options["pacemaker_remote_addr"] == "10.0.0.1"
        assert vm_options["pacemaker_remote_port"] == "3121"
        assert vm_options["pacemaker_remote_timeout"] == "60"
        assert vm_options["custom_meta"] == {"meta": "1"}
        assert vm_options["custom_params"] == {"param": "2"}
        assert vm_options["custom_utilization"] == {"cpu": "2"}

    def test_live_migration_only_counts_when_true(self, real_enable_vm):
        real_enable_vm.rbd.metadata[DST_DISK] = {"_live_migration": "maybe"}
        assert self._added(real_enable_vm)["live_migration"] == "false"

    def test_xml_path_is_derived_from_the_name(self, real_enable_vm):
        expected = os.path.join(vmc.XML_PACEMAKER_PATH, DST + ".xml")
        assert self._added(real_enable_vm)["xml"] == expected

    @pytest.mark.parametrize(
        "key,message",
        [
            ("_pacemaker_meta", "Custom metadata must be a dictionary"),
            ("_pacemaker_params", "Custom params must be a dictionary"),
            (
                "_pacemaker_utilization",
                "Custom utilization must be a dictionary",
            ),
        ],
    )
    def test_non_dict_pacemaker_metadata_is_rejected(
        self, real_enable_vm, key, message
    ):
        real_enable_vm.rbd.metadata[DST_DISK] = {key: json.dumps(["nope"])}
        with pytest.raises(ValueError, match=message):
            vmc.enable_vm(DST)

    def test_invalid_pinned_host_is_rejected(self, real_enable_vm):
        real_enable_vm.rbd.metadata[DST_DISK] = {"_pinned_host": "nowhere"}
        with pytest.raises(Exception, match="not valid hypervisor"):
            vmc.enable_vm(DST)

    def test_invalid_preferred_host_is_rejected(self, real_enable_vm):
        real_enable_vm.rbd.metadata[DST_DISK] = {"_preferred_host": "nowhere"}
        with pytest.raises(Exception, match="not valid hypervisor"):
            vmc.enable_vm(DST)


class TestEnableVmCluster:
    """enable_vm(): what it drives on Pacemaker."""

    def test_already_known_vm_is_left_alone(self, real_enable_vm, caplog):
        real_enable_vm.resources.add(DST)
        with caplog.at_level("WARNING", logger=vmc.logger.name):
            vmc.enable_vm(DST)
        assert "already on the cluster" in caplog.text
        assert real_enable_vm.pacemaker.call_names == ["list_resources"]

    def test_failed_add_is_reported(self, real_enable_vm):
        real_enable_vm.add_vm_fails = True
        with pytest.raises(Exception, match="Could not add VM"):
            vmc.enable_vm(DST)

    def test_observer_location_is_disabled(self, real_enable_vm):
        real_enable_vm.observer = "observer1"
        vmc.enable_vm(DST)
        assert (
            "disable_location",
            "observer1",
        ) in real_enable_vm.pacemaker.calls

    def test_no_observer_disables_nothing(self, real_enable_vm):
        vmc.enable_vm(DST)
        assert "disable_location" not in real_enable_vm.pacemaker.call_names

    def test_remote_node_locations_are_disabled(self, real_enable_vm):
        real_enable_vm.remote_nodes = ["remote1", "remote2"]
        vmc.enable_vm(DST)
        for node in ("remote1", "remote2"):
            assert (
                "disable_location",
                node,
            ) in real_enable_vm.pacemaker.calls

    def test_pinned_host_is_pinned(self, real_enable_vm):
        real_enable_vm.rbd.metadata[DST_DISK] = {"_pinned_host": "hyp1"}
        vmc.enable_vm(DST)
        assert ("pin_location", "hyp1") in real_enable_vm.pacemaker.calls

    def test_preferred_host_becomes_the_default_location(self, real_enable_vm):
        real_enable_vm.rbd.metadata[DST_DISK] = {"_preferred_host": "hyp2"}
        vmc.enable_vm(DST)
        assert ("default_location", "hyp2") in real_enable_vm.pacemaker.calls

    def test_pinned_host_wins_over_preferred(self, real_enable_vm):
        real_enable_vm.rbd.metadata[DST_DISK] = {
            "_pinned_host": "hyp1",
            "_preferred_host": "hyp2",
        }
        vmc.enable_vm(DST)
        names = real_enable_vm.pacemaker.call_names
        assert "pin_location" in names
        assert "default_location" not in names

    def test_no_host_leaves_the_location_free(self, real_enable_vm):
        vmc.enable_vm(DST)
        names = real_enable_vm.pacemaker.call_names
        assert "pin_location" not in names
        assert "default_location" not in names

    def test_crm_commands_are_run(self, real_enable_vm):
        real_enable_vm.rbd.metadata[DST_DISK] = {
            "_crm_config_cmd": "cmd one\ncmd two"
        }
        vmc.enable_vm(DST)
        calls = real_enable_vm.pacemaker.calls
        assert ("run_crm_cmd", "cmd one") in calls
        assert ("run_crm_cmd", "cmd two") in calls

    def test_no_crm_command_runs_nothing(self, real_enable_vm):
        vmc.enable_vm(DST)
        assert "run_crm_cmd" not in real_enable_vm.pacemaker.call_names

    def test_resource_is_managed_and_waited_for(self, real_enable_vm):
        vmc.enable_vm(DST)
        calls = real_enable_vm.pacemaker.calls
        assert ("manage",) in calls
        assert ("wait_for", "Started") in calls

    def test_nostart_skips_the_wait(self, real_enable_vm):
        vmc.enable_vm(DST, nostart=True)
        assert "wait_for" not in real_enable_vm.pacemaker.call_names
        assert ("manage",) in real_enable_vm.pacemaker.calls

    def test_nostart_is_forwarded_to_add_vm(self, real_enable_vm):
        vmc.enable_vm(DST, nostart=True)
        added = [
            call
            for call in real_enable_vm.pacemaker.calls
            if call[0] == "add_vm"
        ]
        assert added[0][2] is True

    def test_success_is_logged(self, real_enable_vm, caplog):
        with caplog.at_level("INFO", logger=vmc.logger.name):
            vmc.enable_vm(DST)
        assert "enabled on the cluster" in caplog.text


class TestRemove:
    """remove(): Pacemaker, then libvirt, then Ceph."""

    def test_vm_is_disabled_first(self, real_remove):
        vmc.remove(SRC)
        assert real_remove.disabled == [SRC]

    def test_defined_vm_is_undefined(self, real_remove):
        vmc.remove(SRC)
        assert ("undefine", SRC) in real_remove.libvirt.calls

    def test_unknown_vm_is_not_undefined(self, real_remove):
        vmc.remove("ghostvm")
        assert "undefine" not in [
            call[0] for call in real_remove.libvirt.calls
        ]

    def test_group_images_are_removed_with_the_group(self, real_remove):
        extra = vmc._additional_disk_name(0, SRC)
        real_remove.rbd.groups[SRC].add(extra)
        real_remove.rbd.images.add(extra)
        vmc.remove(SRC)
        assert ("remove_group", SRC) in real_remove.rbd.calls
        assert real_remove.rbd.images == set()

    def test_system_disk_is_removed_without_a_group(self, real_remove):
        del real_remove.rbd.groups[SRC]
        vmc.remove(SRC)
        assert ("remove_image", SRC_DISK) in real_remove.rbd.calls

    def test_system_disk_missing_from_the_group_is_still_removed(
        self, real_remove
    ):
        real_remove.rbd.groups[SRC] = {vmc._additional_disk_name(0, SRC)}
        vmc.remove(SRC)
        assert ("remove_image", SRC_DISK) in real_remove.rbd.calls

    def test_absent_image_is_not_removed(self, real_remove):
        real_remove.rbd.images.clear()
        vmc.remove(SRC)
        assert "remove_image" not in real_remove.rbd.call_names

    def test_surviving_group_is_reported(self, real_remove):
        real_remove.rbd.undeletable_groups.add(SRC)
        with pytest.raises(Exception, match="Could not remove group"):
            vmc.remove(SRC)

    def test_surviving_image_is_reported(self, real_remove):
        real_remove.rbd.undeletable_images.add(SRC_DISK)
        with pytest.raises(RuntimeError, match="Could not remove image"):
            vmc.remove(SRC)

    def test_success_is_logged(self, real_remove, caplog):
        with caplog.at_level("INFO", logger=vmc.logger.name):
            vmc.remove(SRC)
        assert "removed" in caplog.text


class TestListAllUuids:
    """list_all_uuids(): the UUID index built from the group XMLs."""

    def _with_xml(self, cluster, vm_name, xml):
        cluster.rbd.groups.setdefault(vm_name, set())
        cluster.rbd.metadata.setdefault(vmc.OS_DISK_PREFIX + vm_name, {})[
            "xml"
        ] = xml

    def test_uuids_are_mapped_to_their_vm(self, cluster):
        self._with_xml(cluster, SRC, BASE_XML)
        assert vmc.list_all_uuids() == {
            "11111111-2222-3333-4444-555555555555": SRC
        }

    def test_several_vms_are_listed(self, cluster):
        self._with_xml(cluster, SRC, BASE_XML)
        self._with_xml(
            cluster,
            DST,
            BASE_XML.replace("1111", "2222"),
        )
        assert len(vmc.list_all_uuids()) == 2

    def test_disk_without_xml_is_skipped(self, cluster, caplog):
        with caplog.at_level("WARNING", logger=vmc.logger.name):
            assert vmc.list_all_uuids() == {}
        assert "Could not read UUID" in caplog.text

    def test_malformed_xml_is_skipped(self, cluster, caplog):
        self._with_xml(cluster, SRC, "<domain")
        with caplog.at_level("WARNING", logger=vmc.logger.name):
            assert vmc.list_all_uuids() == {}
        assert "Could not read UUID" in caplog.text

    def test_xml_without_uuid_is_skipped(self, cluster):
        self._with_xml(cluster, SRC, "<domain><name>srcvm</name></domain>")
        assert vmc.list_all_uuids() == {}

    def test_no_group_gives_no_uuid(self, cluster):
        cluster.rbd.groups.clear()
        assert vmc.list_all_uuids() == {}


class TestGetAllDiskNames:
    """_get_all_disk_names(): the group, or the system disk alone."""

    def test_group_images_are_returned(self, cluster):
        extra = vmc._additional_disk_name(0, SRC)
        cluster.rbd.groups[SRC].add(extra)
        assert vmc._get_all_disk_names(cluster.rbd, SRC) == [extra, SRC_DISK]

    def test_without_a_group_only_the_system_disk(self, cluster):
        assert vmc._get_all_disk_names(cluster.rbd, "ghostvm") == [
            vmc.OS_DISK_PREFIX + "ghostvm"
        ]


def snapshot(index, name, timestamp):
    """Build a snapshot as the Ceph bindings report it."""
    return {"id": index, "name": name, "timestamp": timestamp}


class TestPurgeImageByDate:
    """purge_image(date=...): drop what predates a date."""

    OLD = datetime.datetime(2026, 1, 1)
    RECENT = datetime.datetime(2026, 6, 1)
    CUTOFF = datetime.datetime(2026, 3, 1)

    @pytest.fixture(autouse=True)
    def snapshots(self, cluster):
        cluster.rbd.snapshots[SRC_DISK] = [
            snapshot(0, "snap-old", self.OLD),
            snapshot(1, "snap-recent", self.RECENT),
        ]
        return cluster

    def test_date_and_number_are_exclusive(self, cluster):
        with pytest.raises(ValueError, match="Only date or number"):
            vmc.purge_image(SRC, date=self.CUTOFF, number=1)

    def test_date_must_be_a_datetime(self, cluster):
        with pytest.raises(ValueError, match="not datetime"):
            vmc.purge_image(SRC, date="2026-03-01")

    def test_older_snapshots_are_removed(self, cluster):
        vmc.purge_image(SRC, date=self.CUTOFF)
        assert (
            "remove_image_snapshot",
            SRC_DISK,
            "snap-old",
        ) in cluster.rbd.calls

    def test_recent_snapshots_are_kept(self, cluster):
        vmc.purge_image(SRC, date=self.CUTOFF)
        assert (
            "remove_image_snapshot",
            SRC_DISK,
            "snap-recent",
        ) not in cluster.rbd.calls

    def test_every_disk_of_the_group_is_purged(self, cluster):
        extra = vmc._additional_disk_name(0, SRC)
        cluster.rbd.groups[SRC].add(extra)
        cluster.rbd.snapshots[extra] = [snapshot(0, "snap-old", self.OLD)]
        vmc.purge_image(SRC, date=self.CUTOFF)
        assert (
            "remove_image_snapshot",
            extra,
            "snap-old",
        ) in cluster.rbd.calls

    def test_it_is_logged(self, cluster, caplog):
        with caplog.at_level("INFO", logger=vmc.logger.name):
            vmc.purge_image(SRC, date=self.CUTOFF)
        assert "previous to" in caplog.text


class TestPurgeImageByNumber:
    """purge_image(number=...): drop the oldest ones."""

    @pytest.fixture(autouse=True)
    def snapshots(self, cluster):
        cluster.rbd.snapshots[SRC_DISK] = [
            snapshot(index, "snap{}".format(index), None) for index in range(4)
        ]
        return cluster

    @pytest.mark.parametrize("number", [-1, "two", 1.5])
    def test_number_must_be_a_non_negative_integer(self, cluster, number):
        with pytest.raises(ValueError, match="non-negative integer"):
            vmc.purge_image(SRC, number=number)

    def test_the_oldest_are_removed(self, cluster):
        vmc.purge_image(SRC, number=2)
        assert (
            "remove_image_snapshot",
            SRC_DISK,
            "snap0",
        ) in cluster.rbd.calls
        assert (
            "remove_image_snapshot",
            SRC_DISK,
            "snap1",
        ) in cluster.rbd.calls

    def test_the_others_are_kept(self, cluster):
        vmc.purge_image(SRC, number=2)
        assert (
            "remove_image_snapshot",
            SRC_DISK,
            "snap2",
        ) not in cluster.rbd.calls

    def test_removing_them_all_purges_the_image(self, cluster):
        vmc.purge_image(SRC, number=4)
        assert ("purge_image", SRC_DISK) in cluster.rbd.calls

    def test_a_disk_left_behind_catches_up(self, cluster):
        """A disk with more snapshots than the others is realigned.

        That happens when a previous purge failed halfway.
        """
        extra = vmc._additional_disk_name(0, SRC)
        cluster.rbd.groups[SRC].add(extra)
        cluster.rbd.snapshots[extra] = [
            snapshot(index, "extra{}".format(index), None)
            for index in range(6)
        ]
        vmc.purge_image(SRC, number=1)
        removed = [
            call[2]
            for call in cluster.rbd.calls
            if call[0] == "remove_image_snapshot" and call[1] == extra
        ]
        assert removed == ["extra0", "extra1", "extra2"]

    def test_it_is_logged(self, cluster, caplog):
        with caplog.at_level("INFO", logger=vmc.logger.name):
            vmc.purge_image(SRC, number=1)
        assert "First 1 snapshots" in caplog.text


class TestPurgeImageAll:
    """purge_image() with neither date nor number."""

    def test_every_disk_is_purged(self, cluster):
        extra = vmc._additional_disk_name(0, SRC)
        cluster.rbd.groups[SRC].add(extra)
        vmc.purge_image(SRC)
        assert ("purge_image", SRC_DISK) in cluster.rbd.calls
        assert ("purge_image", extra) in cluster.rbd.calls

    def test_it_is_logged(self, cluster, caplog):
        with caplog.at_level("INFO", logger=vmc.logger.name):
            vmc.purge_image(SRC)
        assert "successfully purged" in caplog.text
