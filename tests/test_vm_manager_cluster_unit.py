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

import json

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
    monkeypatch.setattr(
        vmc,
        "Pacemaker",
        type(
            "PacemakerStub",
            (),
            {
                "is_valid_host": staticmethod(
                    lambda host: host in collaborators.valid_hosts
                )
            },
        ),
    )
    monkeypatch.setattr(
        vmc,
        "_create_vm_group",
        lambda name, force=False: collaborators.groups_created.append(
            (name, force)
        ),
    )
    monkeypatch.setattr(vmc, "_configure_vm", collaborators.configure)
    monkeypatch.setattr(
        vmc, "remove", lambda name: collaborators.removed.append(name)
    )
    return collaborators


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

    @pytest.mark.xfail(
        strict=True,
        reason="the rollback loops over src_additional_count, which is only "
        "assigned after the system disk copy. A failure in image_exists, "
        "remove_image or copy_image, or a copy that creates nothing, "
        "therefore raises UnboundLocalError from the except branch and hides "
        "the error that caused the rollback.",
    )
    def test_failed_system_disk_copy_is_reported(self, cluster):
        cluster.rbd.no_create.add(DST_DISK)
        vm_options = options(base_xml=BASE_XML)
        with pytest.raises(Exception, match="Could not create image disk"):
            vmc.clone(vm_options)


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

    @pytest.mark.xfail(
        strict=True,
        reason='the pacemaker checks sit inside the \'if "metadata" in '
        "vm_options' block, so create() accepts a non-dict pacemaker option "
        "whenever no metadata is passed. _configure_vm then stores the string "
        "as JSON, and the next clone of that VM fails on it. clone() "
        "validates the same options unconditionally.",
    )
    def test_pacemaker_options_are_validated_without_metadata(
        self, cluster, create_options
    ):
        vm_options = create_options(pacemaker_meta="not-a-dict")
        with pytest.raises(ValueError, match="pacemaker_meta"):
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
