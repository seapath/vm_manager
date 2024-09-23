# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""
Helper module to manipulate RBD.
"""

import os.path
import logging
import subprocess

from errno import ENOENT
from rados import Rados
from rbd import RBD, Group, Image

logger = logging.getLogger(__name__)


class RbdException(Exception):
    """
    To be used to raise exceptions from this module.
    """


class RbdManager:
    """
    Helper class to manipulate RBD.
    """

    def __init__(
        self, ceph_conf="/etc/ceph/ceph.conf", pool="rbd", namespace=""
    ):
        """
        Class constructor.
        """

        if not os.path.isfile(ceph_conf):
            raise IOError(ENOENT, "Could not find file", ceph_conf)

        self._cluster = Rados(conffile=ceph_conf)
        self._rbd_inst = RBD()

        self._namespace = namespace
        self._pool = pool

        try:
            self._cluster.connect()
            self._ioctx = self._cluster.open_ioctx(self._pool)
            self.set_namespace(self._namespace)
            logger.info("Module has been successfully initialized")
        except RbdException as err:
            logger.warning("Init not successful: " + str(err))
            raise err

    def __enter__(self):
        """
        Start context.
        """
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """
        Close context.
        """
        self.close()

    def close(self):
        """
        Close I/O context.
        """
        self._ioctx.close()

    # Namespace methods
    def list_namespaces(self):
        """
        Return list of all namespaces within the I/O context.
        """
        return self._rbd_inst.namespace_list(self._ioctx)

    def namespace_exists(self, ns):
        """
        Check if I/O context contains the namespace ns.
        """
        return ns == "" or self._rbd_inst.namespace_exists(self._ioctx, ns)

    def create_namespace(self, ns):
        """
        Create a namespace ns on the I/O context.
        """
        self._rbd_inst.namespace_create(self._ioctx, ns)

    def remove_namespace(self, ns):
        """
        Remove image namespace ns from the I/O context. Not possible if it
        is the current namespace.
        """
        if self.get_namespace() == ns:
            raise RbdException("Could not delete the current set namespace")
        self._rbd_inst.namespace_remove(self._ioctx, ns)

    def set_namespace(self, ns):
        """
        Set namespace ns for the I/O context.
        """
        # Create if not exists, otherwise it cannot be used
        if not self.namespace_exists(ns):
            self.create_namespace(ns)
        self._ioctx.set_namespace(ns)

    def get_namespace(self):
        """
        Return current namespace used on the I/O context.
        """
        return self._ioctx.get_namespace()

    # Image methods
    def list_images(self):
        """
        Return a list of all the images from the context.
        """
        return self._rbd_inst.list(self._ioctx)

    def image_exists(self, img):
        """
        Check if an image exists.
        """
        return img in self.list_images()

    def _get_image(self, img):
        """
        Return an image instance for a given img name.
        """
        img_inst = Image(self._ioctx, img)
        if img_inst is None:
            raise RbdException("Could not find image " + img)
        else:
            return img_inst

    def create_image(self, img, size, overwrite=True):
        """
        Create a given size image on the Ceph cluster.
        """
        # Convert size if units specified
        if not isinstance(size, int):
            unit_list = ["B", "K", "M", "G", "T"]
            i = unit_list.index(size[-1])
            size = int(size[:-1]) * 1024**i

        if self.image_exists(img):
            if overwrite:
                self.remove_image(img)
            else:
                raise RbdException("Image " + img + " already exists")

        self._rbd_inst.create(self._ioctx, img, size)
        logger.info("Created image " + img + " of size " + str(size))

    def remove_image(self, img):
        """
        Remove img from Ceph.
        """
        img_inst = self._get_image(img)
        try:
            self.purge_image(img, force=True)
            img_inst.close()
            self._rbd_inst.remove(self._ioctx, img)
            logger.info("Removed image " + img)
        finally:
            img_inst.close()

    def clone_image(self, src_img, dst_img, snap, overwrite=True):
        """
        Clone image src_img to dst_img from a snapshot snap.
        """
        if src_img == dst_img:
            raise ValueError(
                "Source and destination images cannot have the same name "
                + src_img
            )

        if not self.image_exists(src_img):
            raise ValueError("Source image " + src_img + " does not exist")

        if not self.image_snapshot_exists(src_img, snap):
            raise ValueError("Snapshot " + snap + " does not exist")

        if self.image_exists(dst_img):
            if overwrite:
                self.remove_image(dst_img)
            else:
                raise RbdException(
                    "Destination image " + dst_img + " already exists"
                )

        img_inst = self._get_image(src_img)
        try:
            img_inst.protect_snap(snap)
            self._rbd_inst.clone(
                self._ioctx, src_img, snap, self._ioctx, dst_img
            )
            logger.info(
                "Image " + src_img + " has been cloned into " + dst_img
            )
        finally:
            img_inst.close()

    def copy_image(self, src_img, dst_img, overwrite=True, deep=True):
        """
        Create an RBD image copy from src_img named dst_img.
        """
        logger.info("copy " + src_img + " into " + dst_img)
        if src_img == dst_img:
            raise ValueError(
                "Source and destination images cannot have the same name "
                + src_img
            )
        if not self.image_exists(src_img):
            raise ValueError("Source image " + src_img + " does not exist")

        if self.image_exists(dst_img):
            if overwrite:
                self.remove_image(dst_img)
            else:
                raise RbdException(
                    "Destination image " + dst_img + " already exists"
                )
        img_inst = self._get_image(src_img)
        try:
            if deep:
                img_inst.deep_copy(self._ioctx, dst_img)
                logger.info(
                    "Image " + src_img + " has been copied into " + dst_img
                )
            else:
                img_inst.copy(self._ioctx, dst_img)
                logger.info(
                    "Image "
                    + src_img
                    + " has been deep-copied into "
                    + dst_img
                )

        finally:
            img_inst.close()

    def rollback_image(self, img, snap):
        """
        Rollback image to snapshot.
        """
        try:
            img_inst = self._get_image(img)
            img_inst.rollback_to_snap(snap)
        finally:
            img_inst.close()

    def purge_image(self, img, force=False):
        """
        Remove all unprotected snapshots from an image.
        """
        img_inst = self._get_image(img)
        try:
            for snapshot in img_inst.list_snaps():
                snap = snapshot["name"]
                if not img_inst.is_protected_snap(snap):
                    img_inst.remove_snap(snap)
                elif force:  # Force protected images removal
                    img_inst.unprotect_snap(snap)
                    img_inst.remove_snap(snap)
            logger.info("Image " + img + " has been purged")
        finally:
            img_inst.close()

    # Snapshots related methods
    def list_image_snapshots(self, img, flat=True):
        """
        Return a list of all snapshots from an image.
        """
        img_inst = self._get_image(img)
        try:
            if flat:
                return [x["name"] for x in img_inst.list_snaps()]
            else:
                return [
                    {"name": x["name"], "id": x["id"]}
                    for x in img_inst.list_snaps()
                ]
        finally:
            img_inst.close()

    def image_snapshot_exists(self, img, snap):
        """
        Check if snapshot exists on image.
        """
        return snap in self.list_image_snapshots(img)

    def create_image_snapshot(self, img, snap):
        """
        Create snapshot snap from an image img.
        """
        img_inst = self._get_image(img)
        try:
            img_inst.create_snap(snap)
            logger.info("Image " + img + " snapshot " + snap + " created")
        finally:
            img_inst.close()

    def remove_image_snapshot(self, img, snap):
        """
        Remove all snapshots for a given image
        """
        img_inst = self._get_image(img)
        try:
            if img_inst.is_protected_snap(snap):
                img_inst.unprotect_snap(snap)
            img_inst.remove_snap(snap)
            logger.info("Snapshot " + snap + " removed from " + img)
        finally:
            img_inst.close()

    def get_image_snapshot_timestamp(self, img, snap):
        """
        Returns timestamp for a given image snapshot.
        """
        img_inst = self._get_image(img)
        try:
            if isinstance(snap, int):
                return img_inst.get_snap_timestamp(snap)
            else:
                for s in img_inst.list_snaps():
                    if s["name"] == snap:
                        return img_inst.get_snap_timestamp(s["id"])
            raise RbdException("Snapshot " + snap + " not found")
        finally:
            img_inst.close()

    def set_image_snapshot_protected(self, img, snap, protect):
        """
        Set protected state for an image snapshot.
        """
        img_inst = self._get_image(img)
        try:
            if protect != img_inst.is_protected_snap(snap):
                if protect:
                    img_inst.protect_snap(snap)
                else:
                    img_inst.unprotect_snap(snap)

            logger.info(
                "Snapshot "
                + snap
                + " protect state: "
                + str(img_inst.is_protected_snap(snap))
            )

        finally:
            img_inst.close()

    def is_image_snapshot_protected(self, img, snap):
        """
        Check if an image snapshot is protected.
        """
        img_inst = self._get_image(img)
        try:
            return img_inst.is_protected_snap(snap)
        finally:
            img_inst.close()

    # I/O methods
    def write_to_image(self, img, data, pos):
        """
        Write bytearray data to image starting from a given position.
        """
        img_inst = self._get_image(img)
        try:
            return img_inst.write(data, pos)
        finally:
            img_inst.close()

    def read_from_image(self, img, start, end):
        """
        Read bytedata from image within a given range.
        """
        img_inst = self._get_image(img)
        try:
            return img_inst.read(start, end)
        finally:
            img_inst.close()

    # Image metadata access methods
    def list_image_metadata(self, img):
        """
        List all metadata from image.
        """
        img_inst = self._get_image(img)
        try:
            return list(dict(img_inst.metadata_list()).keys())
        finally:
            img_inst.close()

    def set_image_metadata(self, img, key, value):
        """
        Add metadata (key, value) to image img. Use check to ensure 'key'
        is not reserved or contains special charactes.
        """
        img_inst = self._get_image(img)
        try:
            img_inst.metadata_set(key, value)
            logger.info(
                "Metadata " + key + ":" + value + " set to image " + img
            )
        finally:
            img_inst.close()

    def get_image_metadata(self, img, key):
        """
        Return a dictionary with the metadata from image.
        """
        img_inst = self._get_image(img)
        try:
            return img_inst.metadata_get(key)
        finally:
            img_inst.close()

    def remove_image_metadata(self, img, key):
        """
        Remove metadata.
        """
        img_inst = self._get_image(img)
        try:
            img_inst.metadata_remove(key)
        finally:
            img_inst.close()

    # Group methods
    def list_groups(self):
        """
        Lists all rbd groups.
        """
        return self._rbd_inst.group_list(self._ioctx)

    def group_exists(self, group):
        """
        Check if group exists.
        """
        return group in self.list_groups()

    def _get_group(self, group):
        """
        Returns a group instance for a given group name
        """
        group_inst = Group(self._ioctx, group)
        if group_inst is None:
            raise RbdException("Could not find group " + group)
        else:
            return group_inst

    def create_group(self, group):
        """
        Create group and add image inside.
        """
        if self.group_exists(group):
            raise RbdException("Group already exists")

        self._rbd_inst.group_create(self._ioctx, group)
        logger.info("Created group " + group)
        return Group(self._ioctx, group)

    def remove_group(self, group):
        """
        Remove group.
        """
        logger.info("Remove group " + group)
        self._rbd_inst.group_remove(self._ioctx, group)

    def rollback_group(self, group, snap):
        """
        Rollback group to state snapshot.
        """
        group_inst = self._get_group(group)
        group_inst.rollback_to_snap(snap)
        logger.info("Group " + group + " rollbacked to snap " + snap)

    def purge_group(self, group):
        """
        Remove all snapshots from group.
        """
        group_inst = self._get_group(group)
        for snap in self.list_group_snapshots(group):
            group_inst.remove_snap(snap)
        logger.info("Group " + group + " purged")

    # Group snapshot methods
    def list_group_snapshots(self, group):
        """
        List snapshots of a group.
        """
        group_inst = self._get_group(group)
        return [x["name"] for x in group_inst.list_snaps()]

    def group_snapshot_exists(self, group, snap):
        """
        Checks if a snapshot exists in a group.
        """
        return snap in self.list_group_snapshots(group)

    def create_group_snapshot(self, group, snap):
        """
        Create a snapshot snap from group.
        """
        group_inst = self._get_group(group)
        group_inst.create_snap(snap)
        logger.info("Group " + group + " snapshot " + snap + " created")

    def remove_group_snapshot(self, group, snap):
        """
        Remove snapshot snap from group.
        """
        group_inst = self._get_group(group)
        group_inst.remove_snap(snap)
        logger.info("Group " + group + " snapshot " + snap + " removed")

    # Image - group methods
    def list_group_images(self, group):
        """
        Return the list of all the images from the group.
        """
        group_inst = self._get_group(group)
        return [x["name"] for x in group_inst.list_images()]

    def get_image_group(self, img):
        """
        Returns image group.
        """
        img_inst = self._get_image(img)
        try:
            return img_inst.group()["name"]
        finally:
            img_inst.close()

    def is_image_in_group(self, img, group):
        """
        Checks if image img is in group.
        """
        return self.get_image_group(img) == group

    def add_image_to_group(self, img, group):
        """
        Add image to group. Group creation can be forced if not exists.
        """
        img_inst = self._get_image(img)
        try:
            if self.group_exists(group):
                group_inst = self._get_group(group)
                group_inst.add_image(self._ioctx, img)
                logger.info("Image " + img + " added to group " + group)
            else:
                raise RbdException("Group does not exist")
        finally:
            img_inst.close()

    def remove_image_from_group(self, img, group):
        """
        Remove image from group.
        """
        group_inst = self._get_group(group)
        if self.is_image_in_group(img, group):
            group_inst.remove_image(self._ioctx, img)
        else:
            raise RbdException("Image " + img + " is not in group " + group)

    # Image import methods
    def import_qcow2(self, src, dest, progress=False):
        """
        Import image src to qcow2 format (dest).
        """
        # format:  rbd:{pool-name}/{image-name}[@snapshot-name]
        dest = "rbd:" + self._pool + "/" + dest
        args = [
            "/usr/bin/qemu-img",
            "convert",
            "-W",
            "-f",
            "qcow2",
            "-O",
            "raw",
            src,
            dest,
        ]
        if progress:
            args.append("-p")
        subprocess.run(args, check=True)
