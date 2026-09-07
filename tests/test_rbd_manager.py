# Copyright (C) 2026, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""
Unit tests for the RbdManager helper, with no Ceph.

Every other test file replaces RbdManager as a whole, so the stubs
installed by tests/ceph_stubs.py can keep raising on use: a test that
reaches real Ceph code fails loudly instead of passing against a fake.

This file is the exception, because testing RbdManager means running its
real code, which builds Rados, RBD, Image and Group for real. The
fixtures below therefore replace those four names inside
vm_manager.helpers.rbd_manager, and only there, for the duration of a
test. Every other test file keeps seeing the stubs that raise.

The fakes hold one shared FakeCeph state. Image and Group reach it
through the I/O context they are handed, the way the real bindings do,
so the code under test wires them together exactly as it would in
production.

The tests that drive a real cluster live in
vm_manager/helpers/tests/rbd_manager/ and are run by hand.
"""

import pytest

from vm_manager.helpers import rbd_manager
from vm_manager.helpers.rbd_manager import RbdManager, RbdException

POOL = "rbd"
IMG = "system_vm1"
DST = "system_vm2"
GROUP = "vm1"


class ImageNotFound(Exception):
    """Raised when a fake Image is built for an absent image.

    The real rbd.Image constructor raises rbd.ImageNotFound in that
    situation. The name matters less than the fact that it raises.
    """


class ImageState:
    """What the fake cluster remembers about one image."""

    def __init__(self, size=0):
        self.size = size
        # Each snapshot is a dict, as the bindings report them.
        self.snaps = []
        self.metadata = {}
        self.data = bytearray(1024)
        self.group = None
        self.next_snap_id = 0

    def find_snap(self, name):
        for snap in self.snaps:
            if snap["name"] == name:
                return snap
        raise KeyError(name)


class FakeCeph:
    """The state the fake bindings share.

    Tests set it up before the call and read it back after, so the
    assertions are on what Ceph would hold rather than on a call log.
    """

    def __init__(self):
        self.namespaces = set()
        self.images = {}
        self.groups = {}
        self.connected = False
        self.shut_down = False
        # Names whose Image constructor must fail, to simulate an image
        # that disappears between two calls.
        self.unopenable = set()

    def add_image(self, name, size=0):
        self.images[name] = ImageState(size)
        return self.images[name]

    def add_snap(self, img, name, protected=False, timestamp=None):
        state = self.images[img]
        snap = {
            "id": state.next_snap_id,
            "name": name,
            "protected": protected,
            "timestamp": timestamp,
        }
        state.next_snap_id += 1
        state.snaps.append(snap)
        return snap


class FakeIoctx:
    """The I/O context, and the way the fakes reach the shared state."""

    def __init__(self, ceph, pool):
        self.ceph = ceph
        self.pool = pool
        self.namespace = ""
        self.closed = False

    def set_namespace(self, ns):
        self.namespace = ns

    def get_namespace(self):
        return self.namespace

    def close(self):
        self.closed = True


class FakeRados:
    """Stand-in for rados.Rados."""

    def __init__(self, ceph, conffile=None):
        self.ceph = ceph
        self.conffile = conffile
        self.ioctxs = []

    def connect(self):
        self.ceph.connected = True

    def open_ioctx(self, pool):
        ioctx = FakeIoctx(self.ceph, pool)
        self.ioctxs.append(ioctx)
        return ioctx

    def shutdown(self):
        self.ceph.shut_down = True


class FakeRBD:
    """Stand-in for rbd.RBD, the pool-level operations."""

    def __init__(self, ceph):
        self.ceph = ceph

    # Namespaces
    def namespace_list(self, ioctx):
        return sorted(self.ceph.namespaces)

    def namespace_exists(self, ioctx, ns):
        return ns in self.ceph.namespaces

    def namespace_create(self, ioctx, ns):
        self.ceph.namespaces.add(ns)

    def namespace_remove(self, ioctx, ns):
        self.ceph.namespaces.discard(ns)

    # Images
    def list(self, ioctx):
        return sorted(self.ceph.images)

    def create(self, ioctx, name, size):
        self.ceph.add_image(name, size)

    def remove(self, ioctx, name):
        self.ceph.images.pop(name, None)

    def clone(self, src_ioctx, src, snap, dst_ioctx, dst):
        self.ceph.add_image(dst, self.ceph.images[src].size)

    # Groups
    def group_list(self, ioctx):
        return sorted(self.ceph.groups)

    def group_create(self, ioctx, group):
        self.ceph.groups[group] = []

    def group_remove(self, ioctx, group):
        self.ceph.groups.pop(group, None)


class FakeImage:
    """Stand-in for rbd.Image, built as Image(ioctx, name)."""

    def __init__(self, ioctx, name):
        self.ceph = ioctx.ceph
        self.name = name
        if name in self.ceph.unopenable or name not in self.ceph.images:
            raise ImageNotFound(name)
        self.state = self.ceph.images[name]
        self.closed = False
        self.close_count = 0

    def close(self):
        self.closed = True
        self.close_count += 1

    # Snapshots
    def list_snaps(self):
        return [dict(snap) for snap in self.state.snaps]

    def create_snap(self, snap):
        self.ceph.add_snap(self.name, snap)

    def remove_snap(self, snap):
        self.state.snaps = [s for s in self.state.snaps if s["name"] != snap]

    def is_protected_snap(self, snap):
        return self.state.find_snap(snap)["protected"]

    def protect_snap(self, snap):
        self.state.find_snap(snap)["protected"] = True

    def unprotect_snap(self, snap):
        self.state.find_snap(snap)["protected"] = False

    def get_snap_timestamp(self, snap_id):
        for snap in self.state.snaps:
            if snap["id"] == snap_id:
                return snap["timestamp"]
        raise KeyError(snap_id)

    def rollback_to_snap(self, snap):
        self.state.rolled_back_to = snap

    # Copies
    def deep_copy(self, ioctx, dst):
        ioctx.ceph.add_image(dst, self.state.size)
        ioctx.ceph.images[dst].deep = True

    def copy(self, ioctx, dst):
        ioctx.ceph.add_image(dst, self.state.size)
        ioctx.ceph.images[dst].deep = False

    # I/O
    def write(self, data, pos):
        end = pos + len(data)
        self.state.data[pos:end] = data
        return len(data)

    def read(self, start, end):
        stop = start + end
        return bytes(self.state.data[start:stop])

    # Metadata
    def metadata_list(self):
        return list(self.state.metadata.items())

    def metadata_set(self, key, value):
        self.state.metadata[key] = value

    def metadata_get(self, key):
        return self.state.metadata[key]

    def metadata_remove(self, key):
        del self.state.metadata[key]

    def group(self):
        return {"name": self.state.group or ""}


class FakeGroup:
    """Stand-in for rbd.Group, built as Group(ioctx, name)."""

    def __init__(self, ioctx, name):
        self.ceph = ioctx.ceph
        self.name = name
        self.snaps = []

    def list_images(self):
        return [
            {"name": img}
            for img in sorted(self.ceph.groups.get(self.name, []))
        ]

    def add_image(self, ioctx, img):
        self.ceph.groups.setdefault(self.name, []).append(img)
        self.ceph.images[img].group = self.name

    def remove_image(self, ioctx, img):
        self.ceph.groups[self.name].remove(img)
        self.ceph.images[img].group = None

    def list_snaps(self):
        return [{"name": snap} for snap in self._snaps()]

    def _snaps(self):
        return self.ceph.groups.setdefault(self.name + "@snaps", [])

    def create_snap(self, snap):
        self._snaps().append(snap)

    def remove_snap(self, snap):
        self._snaps().remove(snap)

    def rollback_to_snap(self, snap):
        self.ceph.rolled_back = (self.name, snap)


class FakeSubprocess:
    """The one subprocess entry point the helper uses."""

    def __init__(self):
        self.calls = []

    def run(self, args, **kwargs):
        self.calls.append((args, kwargs))

    @property
    def command(self):
        assert len(self.calls) == 1, "expected one run(), got {}".format(
            len(self.calls)
        )
        return self.calls[0][0]


@pytest.fixture
def ceph(monkeypatch):
    """Replace the four Ceph bindings inside rbd_manager, and only there."""
    state = FakeCeph()
    monkeypatch.setattr(
        rbd_manager, "Rados", lambda conffile=None: FakeRados(state, conffile)
    )
    monkeypatch.setattr(rbd_manager, "RBD", lambda: FakeRBD(state))
    monkeypatch.setattr(rbd_manager, "Image", FakeImage)
    monkeypatch.setattr(rbd_manager, "Group", FakeGroup)
    return state


@pytest.fixture
def conf(tmp_path):
    """A real ceph.conf, so the existence check runs for real."""
    path = tmp_path / "ceph.conf"
    path.write_text("[global]\n")
    return str(path)


@pytest.fixture
def rbd(ceph, conf):
    """An RbdManager on the fake cluster, with one image in one group."""
    ceph.add_image(IMG, 1024)
    ceph.groups[GROUP] = [IMG]
    ceph.images[IMG].group = GROUP
    return RbdManager(ceph_conf=conf, pool=POOL)


@pytest.fixture
def qemu_img(monkeypatch):
    """Replace the subprocess module import_qcow2 uses."""
    fake = FakeSubprocess()
    monkeypatch.setattr(rbd_manager, "subprocess", fake)
    return fake


class TestConstruction:
    """The constructor connects, opens the pool and sets the namespace."""

    def test_a_missing_ceph_conf_is_reported(self, ceph, tmp_path):
        with pytest.raises(IOError, match="Could not find file"):
            RbdManager(ceph_conf=str(tmp_path / "absent.conf"))

    def test_the_cluster_is_connected(self, ceph, conf):
        RbdManager(ceph_conf=conf)
        assert ceph.connected is True

    def test_the_pool_is_opened(self, ceph, conf):
        manager = RbdManager(ceph_conf=conf, pool="mypool")
        assert manager._ioctx.pool == "mypool"

    def test_the_default_namespace_is_empty(self, ceph, conf):
        manager = RbdManager(ceph_conf=conf)
        assert manager.get_namespace() == ""

    def test_a_named_namespace_is_created_and_set(self, ceph, conf):
        manager = RbdManager(ceph_conf=conf, namespace="ns1")
        assert "ns1" in ceph.namespaces
        assert manager.get_namespace() == "ns1"

    def test_success_is_logged(self, ceph, conf, caplog):
        with caplog.at_level("INFO", logger=rbd_manager.logger.name):
            RbdManager(ceph_conf=conf)
        assert "successfully initialized" in caplog.text


class TestContext:
    """The context manager closes the I/O context and the cluster."""

    def test_it_yields_the_instance(self, ceph, conf):
        with RbdManager(ceph_conf=conf) as manager:
            assert isinstance(manager, RbdManager)

    def test_leaving_closes_both(self, ceph, conf):
        with RbdManager(ceph_conf=conf) as manager:
            ioctx = manager._ioctx
        assert ioctx.closed is True
        assert ceph.shut_down is True


class TestNamespaces:
    """The namespace methods."""

    def test_namespaces_are_listed(self, rbd, ceph):
        ceph.namespaces.update({"ns1", "ns2"})
        assert rbd.list_namespaces() == ["ns1", "ns2"]

    def test_the_empty_namespace_always_exists(self, rbd):
        assert rbd.namespace_exists("") is True

    def test_an_unknown_namespace_does_not_exist(self, rbd):
        assert rbd.namespace_exists("ns1") is False

    def test_a_created_namespace_exists(self, rbd):
        rbd.create_namespace("ns1")
        assert rbd.namespace_exists("ns1") is True

    def test_a_namespace_is_removed(self, rbd, ceph):
        ceph.namespaces.add("ns1")
        rbd.remove_namespace("ns1")
        assert "ns1" not in ceph.namespaces

    def test_the_current_namespace_cannot_be_removed(self, ceph, conf):
        manager = RbdManager(ceph_conf=conf, namespace="ns1")
        with pytest.raises(RbdException, match="current set namespace"):
            manager.remove_namespace("ns1")
        assert "ns1" in ceph.namespaces

    def test_setting_an_absent_namespace_creates_it(self, rbd, ceph):
        rbd.set_namespace("ns2")
        assert "ns2" in ceph.namespaces
        assert rbd.get_namespace() == "ns2"

    def test_setting_an_existing_namespace_does_not_recreate_it(
        self, rbd, ceph
    ):
        ceph.namespaces.add("ns2")
        rbd.set_namespace("ns2")
        assert rbd.get_namespace() == "ns2"


class TestListImages:
    """list_images() and image_exists()."""

    def test_the_images_are_listed(self, rbd, ceph):
        ceph.add_image(DST)
        assert rbd.list_images() == [IMG, DST]

    def test_a_known_image_exists(self, rbd):
        assert rbd.image_exists(IMG) is True

    def test_an_unknown_image_does_not_exist(self, rbd):
        assert rbd.image_exists("absent") is False


class TestCreateImage:
    """create_image(), including the size unit conversion."""

    def test_an_integer_size_is_used_as_is(self, rbd, ceph):
        rbd.create_image(DST, 4096)
        assert ceph.images[DST].size == 4096

    @pytest.mark.parametrize(
        "size, expected",
        [
            ("512B", 512),
            ("4K", 4 * 1024),
            ("10M", 10 * 1024 ** 2),
            ("2G", 2 * 1024 ** 3),
            ("1T", 1024 ** 4),
        ],
    )
    def test_a_unit_suffix_is_converted(self, rbd, ceph, size, expected):
        rbd.create_image(DST, size)
        assert ceph.images[DST].size == expected

    def test_an_unknown_unit_is_refused(self, rbd):
        with pytest.raises(ValueError):
            rbd.create_image(DST, "10X")

    def test_an_existing_image_is_overwritten_by_default(self, rbd, ceph):
        rbd.create_image(IMG, 2048)
        assert ceph.images[IMG].size == 2048

    def test_an_existing_image_is_kept_without_overwrite(self, rbd, ceph):
        with pytest.raises(RbdException, match="already exists"):
            rbd.create_image(IMG, 2048, overwrite=False)
        assert ceph.images[IMG].size == 1024

    def test_the_creation_is_logged(self, rbd, caplog):
        with caplog.at_level("INFO", logger=rbd_manager.logger.name):
            rbd.create_image(DST, 4096)
        assert "Created image " + DST in caplog.text


class TestRemoveImage:
    """remove_image(): purge the snapshots, then drop the image."""

    def test_the_image_is_gone(self, rbd, ceph):
        rbd.remove_image(IMG)
        assert IMG not in ceph.images

    def test_protected_snapshots_are_purged_too(self, rbd, ceph):
        ceph.add_snap(IMG, "snap1", protected=True)
        rbd.remove_image(IMG)
        assert IMG not in ceph.images

    def test_an_absent_image_is_reported(self, rbd):
        with pytest.raises(ImageNotFound):
            rbd.remove_image("absent")

    def test_the_removal_is_logged(self, rbd, caplog):
        with caplog.at_level("INFO", logger=rbd_manager.logger.name):
            rbd.remove_image(IMG)
        assert "Removed image " + IMG in caplog.text


class TestCloneImage:
    """clone_image(): a copy-on-write clone from a snapshot."""

    @pytest.fixture
    def snapped(self, rbd, ceph):
        """The source image carries a snapshot to clone from."""
        ceph.add_snap(IMG, "snap1")
        return rbd

    def test_the_clone_is_created(self, snapped, ceph):
        snapped.clone_image(IMG, DST, "snap1")
        assert DST in ceph.images

    def test_the_source_snapshot_is_protected_first(self, snapped, ceph):
        snapped.clone_image(IMG, DST, "snap1")
        assert ceph.images[IMG].find_snap("snap1")["protected"] is True

    def test_the_same_name_is_refused(self, snapped):
        with pytest.raises(ValueError, match="same name"):
            snapped.clone_image(IMG, IMG, "snap1")

    def test_an_absent_source_is_refused(self, snapped):
        with pytest.raises(ValueError, match="Source image"):
            snapped.clone_image("absent", DST, "snap1")

    def test_an_absent_snapshot_is_refused(self, snapped):
        with pytest.raises(ValueError, match="Snapshot"):
            snapped.clone_image(IMG, DST, "absent")

    def test_an_existing_destination_is_overwritten_by_default(
        self, snapped, ceph
    ):
        ceph.add_image(DST, 99)
        snapped.clone_image(IMG, DST, "snap1")
        assert ceph.images[DST].size == 1024

    def test_an_existing_destination_is_kept_without_overwrite(
        self, snapped, ceph
    ):
        ceph.add_image(DST, 99)
        with pytest.raises(RbdException, match="Destination image"):
            snapped.clone_image(IMG, DST, "snap1", overwrite=False)
        assert ceph.images[DST].size == 99

    def test_the_clone_is_logged(self, snapped, caplog):
        with caplog.at_level("INFO", logger=rbd_manager.logger.name):
            snapped.clone_image(IMG, DST, "snap1")
        assert "has been cloned into " + DST in caplog.text


class TestCopyImage:
    """copy_image(): a full copy, deep or shallow."""

    def test_a_deep_copy_by_default(self, rbd, ceph):
        rbd.copy_image(IMG, DST)
        assert ceph.images[DST].deep is True

    def test_a_shallow_copy_when_asked(self, rbd, ceph):
        rbd.copy_image(IMG, DST, deep=False)
        assert ceph.images[DST].deep is False

    def test_the_same_name_is_refused(self, rbd):
        with pytest.raises(ValueError, match="same name"):
            rbd.copy_image(IMG, IMG)

    def test_an_absent_source_is_refused(self, rbd):
        with pytest.raises(ValueError, match="Source image"):
            rbd.copy_image("absent", DST)

    def test_an_existing_destination_is_overwritten_by_default(
        self, rbd, ceph
    ):
        ceph.add_image(DST, 99)
        rbd.copy_image(IMG, DST)
        assert ceph.images[DST].size == 1024

    def test_an_existing_destination_is_kept_without_overwrite(
        self, rbd, ceph
    ):
        ceph.add_image(DST, 99)
        with pytest.raises(RbdException, match="Destination image"):
            rbd.copy_image(IMG, DST, overwrite=False)
        assert ceph.images[DST].size == 99

    def test_the_copy_is_logged(self, rbd, caplog):
        with caplog.at_level("INFO", logger=rbd_manager.logger.name):
            rbd.copy_image(IMG, DST)
        assert "copy " + IMG + " into " + DST in caplog.text


class TestPurgeImage:
    """purge_image(): drop the snapshots, protected ones only on force."""

    def test_unprotected_snapshots_are_removed(self, rbd, ceph):
        ceph.add_snap(IMG, "snap1")
        rbd.purge_image(IMG)
        assert ceph.images[IMG].snaps == []

    def test_protected_snapshots_survive_without_force(self, rbd, ceph):
        ceph.add_snap(IMG, "snap1", protected=True)
        rbd.purge_image(IMG)
        assert [s["name"] for s in ceph.images[IMG].snaps] == ["snap1"]

    def test_force_removes_protected_snapshots_too(self, rbd, ceph):
        ceph.add_snap(IMG, "snap1", protected=True)
        rbd.purge_image(IMG, force=True)
        assert ceph.images[IMG].snaps == []

    def test_the_purge_is_logged(self, rbd, caplog):
        with caplog.at_level("INFO", logger=rbd_manager.logger.name):
            rbd.purge_image(IMG)
        assert "has been purged" in caplog.text


class TestImageSnapshots:
    """The per-image snapshot methods."""

    def test_snapshot_names_are_listed_flat(self, rbd, ceph):
        ceph.add_snap(IMG, "snap1")
        ceph.add_snap(IMG, "snap2")
        assert rbd.list_image_snapshots(IMG) == ["snap1", "snap2"]

    def test_the_non_flat_listing_carries_the_ids(self, rbd, ceph):
        ceph.add_snap(IMG, "snap1")
        assert rbd.list_image_snapshots(IMG, flat=False) == [
            {"name": "snap1", "id": 0}
        ]

    def test_a_known_snapshot_exists(self, rbd, ceph):
        ceph.add_snap(IMG, "snap1")
        assert rbd.image_snapshot_exists(IMG, "snap1") is True

    def test_an_unknown_snapshot_does_not_exist(self, rbd):
        assert rbd.image_snapshot_exists(IMG, "absent") is False

    def test_a_snapshot_is_created(self, rbd, ceph):
        rbd.create_image_snapshot(IMG, "snap1")
        assert [s["name"] for s in ceph.images[IMG].snaps] == ["snap1"]

    def test_a_snapshot_is_removed(self, rbd, ceph):
        ceph.add_snap(IMG, "snap1")
        rbd.remove_image_snapshot(IMG, "snap1")
        assert ceph.images[IMG].snaps == []

    def test_a_protected_snapshot_is_unprotected_before_removal(
        self, rbd, ceph
    ):
        ceph.add_snap(IMG, "snap1", protected=True)
        rbd.remove_image_snapshot(IMG, "snap1")
        assert ceph.images[IMG].snaps == []

    def test_the_creation_is_logged(self, rbd, caplog):
        with caplog.at_level("INFO", logger=rbd_manager.logger.name):
            rbd.create_image_snapshot(IMG, "snap1")
        assert "snapshot snap1 created" in caplog.text

    def test_the_removal_is_logged(self, rbd, ceph, caplog):
        ceph.add_snap(IMG, "snap1")
        with caplog.at_level("INFO", logger=rbd_manager.logger.name):
            rbd.remove_image_snapshot(IMG, "snap1")
        assert "Snapshot snap1 removed from " + IMG in caplog.text


class TestSnapshotTimestamp:
    """get_image_snapshot_timestamp(), by id or by name."""

    def test_a_snapshot_id_is_looked_up_directly(self, rbd, ceph):
        ceph.add_snap(IMG, "snap1", timestamp="ts1")
        assert rbd.get_image_snapshot_timestamp(IMG, 0) == "ts1"

    def test_a_snapshot_name_is_resolved_first(self, rbd, ceph):
        ceph.add_snap(IMG, "snap1", timestamp="ts1")
        ceph.add_snap(IMG, "snap2", timestamp="ts2")
        assert rbd.get_image_snapshot_timestamp(IMG, "snap2") == "ts2"

    def test_an_unknown_name_is_reported(self, rbd, ceph):
        ceph.add_snap(IMG, "snap1", timestamp="ts1")
        with pytest.raises(RbdException, match="not found"):
            rbd.get_image_snapshot_timestamp(IMG, "absent")


class TestSnapshotProtection:
    """set_image_snapshot_protected() and is_image_snapshot_protected()."""

    def test_an_unprotected_snapshot_is_protected(self, rbd, ceph):
        ceph.add_snap(IMG, "snap1")
        rbd.set_image_snapshot_protected(IMG, "snap1", True)
        assert rbd.is_image_snapshot_protected(IMG, "snap1") is True

    def test_a_protected_snapshot_is_unprotected(self, rbd, ceph):
        ceph.add_snap(IMG, "snap1", protected=True)
        rbd.set_image_snapshot_protected(IMG, "snap1", False)
        assert rbd.is_image_snapshot_protected(IMG, "snap1") is False

    def test_setting_the_state_it_already_has_is_a_no_op(self, rbd, ceph):
        ceph.add_snap(IMG, "snap1", protected=True)
        rbd.set_image_snapshot_protected(IMG, "snap1", True)
        assert rbd.is_image_snapshot_protected(IMG, "snap1") is True

    def test_the_resulting_state_is_logged(self, rbd, ceph, caplog):
        ceph.add_snap(IMG, "snap1")
        with caplog.at_level("INFO", logger=rbd_manager.logger.name):
            rbd.set_image_snapshot_protected(IMG, "snap1", True)
        assert "protect state: True" in caplog.text


class TestImageIO:
    """write_to_image() and read_from_image()."""

    def test_what_is_written_is_read_back(self, rbd):
        rbd.write_to_image(IMG, b"seapath", 10)
        assert rbd.read_from_image(IMG, 10, 7) == b"seapath"

    def test_the_written_length_is_returned(self, rbd):
        assert rbd.write_to_image(IMG, b"seapath", 0) == 7


class TestImageMetadata:
    """The four image metadata methods."""

    def test_metadata_keys_are_listed(self, rbd, ceph):
        ceph.images[IMG].metadata = {"key1": "v1", "key2": "v2"}
        assert rbd.list_image_metadata(IMG) == ["key1", "key2"]

    def test_a_value_is_written_and_read_back(self, rbd):
        rbd.set_image_metadata(IMG, "key1", "v1")
        assert rbd.get_image_metadata(IMG, "key1") == "v1"

    def test_a_value_is_removed(self, rbd, ceph):
        ceph.images[IMG].metadata = {"key1": "v1"}
        rbd.remove_image_metadata(IMG, "key1")
        assert ceph.images[IMG].metadata == {}

    def test_an_unknown_key_is_reported(self, rbd):
        with pytest.raises(KeyError):
            rbd.get_image_metadata(IMG, "absent")

    def test_writing_is_logged(self, rbd, caplog):
        with caplog.at_level("INFO", logger=rbd_manager.logger.name):
            rbd.set_image_metadata(IMG, "key1", "v1")
        assert "Metadata key1:v1 set to image " + IMG in caplog.text


class TestGroups:
    """The group methods."""

    def test_groups_are_listed(self, rbd, ceph):
        ceph.groups["vm2"] = []
        assert rbd.list_groups() == [GROUP, "vm2"]

    def test_a_known_group_exists(self, rbd):
        assert rbd.group_exists(GROUP) is True

    def test_an_unknown_group_does_not_exist(self, rbd):
        assert rbd.group_exists("absent") is False

    def test_a_group_is_created(self, rbd, ceph):
        rbd.create_group("vm2")
        assert "vm2" in ceph.groups

    def test_an_existing_group_is_refused(self, rbd):
        with pytest.raises(RbdException, match="Group already exists"):
            rbd.create_group(GROUP)

    def test_the_created_group_is_returned(self, rbd):
        assert rbd.create_group("vm2").name == "vm2"

    def test_a_group_is_removed(self, rbd, ceph):
        rbd.remove_group(GROUP)
        assert GROUP not in ceph.groups

    def test_the_creation_is_logged(self, rbd, caplog):
        with caplog.at_level("INFO", logger=rbd_manager.logger.name):
            rbd.create_group("vm2")
        assert "Created group vm2" in caplog.text

    def test_the_removal_is_logged(self, rbd, caplog):
        with caplog.at_level("INFO", logger=rbd_manager.logger.name):
            rbd.remove_group(GROUP)
        assert "Remove group " + GROUP in caplog.text


class TestGroupSnapshots:
    """The group snapshot methods."""

    def test_a_snapshot_is_created(self, rbd):
        rbd.create_group_snapshot(GROUP, "snap1")
        assert rbd.list_group_snapshots(GROUP) == ["snap1"]

    def test_a_snapshot_is_removed(self, rbd):
        rbd.create_group_snapshot(GROUP, "snap1")
        rbd.remove_group_snapshot(GROUP, "snap1")
        assert rbd.list_group_snapshots(GROUP) == []

    def test_a_known_snapshot_exists(self, rbd):
        rbd.create_group_snapshot(GROUP, "snap1")
        assert rbd.group_snapshot_exists(GROUP, "snap1") is True

    def test_an_unknown_snapshot_does_not_exist(self, rbd):
        assert rbd.group_snapshot_exists(GROUP, "absent") is False

    def test_a_group_is_rolled_back(self, rbd, ceph):
        rbd.rollback_group(GROUP, "snap1")
        assert ceph.rolled_back == (GROUP, "snap1")

    def test_a_purge_removes_every_snapshot(self, rbd):
        rbd.create_group_snapshot(GROUP, "snap1")
        rbd.create_group_snapshot(GROUP, "snap2")
        rbd.purge_group(GROUP)
        assert rbd.list_group_snapshots(GROUP) == []

    def test_the_rollback_is_logged(self, rbd, caplog):
        with caplog.at_level("INFO", logger=rbd_manager.logger.name):
            rbd.rollback_group(GROUP, "snap1")
        assert "rollbacked to snap snap1" in caplog.text

    def test_the_purge_is_logged(self, rbd, caplog):
        with caplog.at_level("INFO", logger=rbd_manager.logger.name):
            rbd.purge_group(GROUP)
        assert "purged" in caplog.text

    def test_the_snapshot_creation_is_logged(self, rbd, caplog):
        with caplog.at_level("INFO", logger=rbd_manager.logger.name):
            rbd.create_group_snapshot(GROUP, "snap1")
        assert "snapshot snap1 created" in caplog.text

    def test_the_snapshot_removal_is_logged(self, rbd, caplog):
        rbd.create_group_snapshot(GROUP, "snap1")
        with caplog.at_level("INFO", logger=rbd_manager.logger.name):
            rbd.remove_group_snapshot(GROUP, "snap1")
        assert "snapshot snap1 removed" in caplog.text


class TestImagesInGroups:
    """The methods tying an image to a group."""

    def test_the_group_images_are_listed(self, rbd):
        assert rbd.list_group_images(GROUP) == [IMG]

    def test_the_group_of_an_image_is_returned(self, rbd):
        assert rbd.get_image_group(IMG) == GROUP

    def test_an_image_without_a_group_reports_an_empty_name(self, rbd, ceph):
        ceph.add_image(DST)
        assert rbd.get_image_group(DST) == ""

    def test_an_image_is_recognised_in_its_group(self, rbd):
        assert rbd.is_image_in_group(IMG, GROUP) is True

    def test_an_image_is_not_in_another_group(self, rbd, ceph):
        ceph.groups["vm2"] = []
        assert rbd.is_image_in_group(IMG, "vm2") is False

    def test_an_image_is_added_to_a_group(self, rbd, ceph):
        ceph.add_image(DST)
        rbd.add_image_to_group(DST, GROUP)
        assert rbd.list_group_images(GROUP) == [IMG, DST]

    def test_adding_to_an_absent_group_is_refused(self, rbd, ceph):
        ceph.add_image(DST)
        with pytest.raises(RbdException, match="Group does not exist"):
            rbd.add_image_to_group(DST, "absent")

    def test_an_image_is_removed_from_its_group(self, rbd):
        rbd.remove_image_from_group(IMG, GROUP)
        assert rbd.list_group_images(GROUP) == []

    def test_removing_an_image_that_is_not_in_the_group_is_refused(
        self, rbd, ceph
    ):
        ceph.add_image(DST)
        with pytest.raises(RbdException, match="is not in group"):
            rbd.remove_image_from_group(DST, GROUP)

    def test_the_addition_is_logged(self, rbd, ceph, caplog):
        ceph.add_image(DST)
        with caplog.at_level("INFO", logger=rbd_manager.logger.name):
            rbd.add_image_to_group(DST, GROUP)
        assert "added to group " + GROUP in caplog.text


class TestImportQcow2:
    """import_qcow2(): the qemu-img call that fills an image."""

    def test_the_conversion_command(self, rbd, qemu_img):
        rbd.import_qcow2("/tmp/disk.qcow2", IMG)
        assert qemu_img.command == [
            "/usr/bin/qemu-img",
            "convert",
            "-W",
            "-f",
            "qcow2",
            "-O",
            "raw",
            "/tmp/disk.qcow2",
            "rbd:" + POOL + "/" + IMG,
        ]

    def test_the_destination_carries_the_pool(self, ceph, conf, qemu_img):
        manager = RbdManager(ceph_conf=conf, pool="mypool")
        manager.import_qcow2("/tmp/disk.qcow2", IMG)
        assert qemu_img.command[-1] == "rbd:mypool/" + IMG

    def test_progress_adds_the_flag(self, rbd, qemu_img):
        rbd.import_qcow2("/tmp/disk.qcow2", IMG, progress=True)
        assert qemu_img.command[-1] == "-p"

    def test_a_failure_is_not_swallowed(self, rbd, qemu_img):
        rbd.import_qcow2("/tmp/disk.qcow2", IMG)
        assert qemu_img.calls[0][1]["check"] is True


class TestRollbackImage:
    """rollback_image(): restore an image to one of its snapshots."""

    def test_the_image_is_rolled_back(self, rbd, ceph):
        ceph.add_snap(IMG, "snap1")
        rbd.rollback_image(IMG, "snap1")
        assert ceph.images[IMG].rolled_back_to == "snap1"
