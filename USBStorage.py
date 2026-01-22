import os
import subprocess
import config
import shutil
import time


class USBStorage:
    @staticmethod
    def image_create():
        if os.path.exists(config.DATA_IMAGE):
            return

        if shutil.which("fallocate"):
            # try fast allocation first
            subprocess.run(
                ["fallocate", "-l", f"{config.IMAGE_SIZE_MB}M", config.DATA_IMAGE], check=True
            )
        else:
            # fallback to dd (slower but reliable)
            subprocess.run(
                [
                    "dd",
                    "if=/dev/zero",
                    f"of={config.DATA_IMAGE}",
                    "bs=1M",
                    f"count={config.IMAGE_SIZE_MB}",
                ],
                check=True,
            )

        # Prefer creating a partition table
        if shutil.which("losetup") and shutil.which("parted") and shutil.which("mkfs.vfat"):
            loop = (
                subprocess.run(
                    ["losetup", "-f", "--show", config.DATA_IMAGE],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                .stdout.strip()
            )

            try:
                # create msdos label and a single FAT32 partition
                subprocess.run(
                    ["parted", "-s", loop, "mklabel", "msdos"], check=True)
                subprocess.run(["parted", "-s", loop, "mkpart",
                               "primary", "fat32", "1MiB", "100%"], check=True)

                # let kernel re-scan partitions; partprobe may help
                subprocess.run(["partprobe", loop], check=False)

                # partition node can be /dev/loopXp1 or /dev/loopX1 depending on system
                part1 = loop + \
                    "p1" if os.path.exists(loop + "p1") else loop + "1"

                # wait briefly for device node
                for _ in range(20):
                    if os.path.exists(part1):
                        break
                    time.sleep(0.1)

                subprocess.run(["mkfs.vfat", part1], check=True)
            finally:
                subprocess.run(["losetup", "-d", loop], check=False)
        else:
            subprocess.run(["mkfs.vfat", config.DATA_IMAGE], check=True)

    @staticmethod
    def image_delete():
        if os.path.exists(config.DATA_IMAGE):
            os.remove(config.DATA_IMAGE)

    @staticmethod
    def image_exists():
        return os.path.exists(config.DATA_IMAGE)

    @staticmethod
    def mount():
        os.makedirs(config.DATA_DIR, exist_ok=True)
        # Prefer using losetup with partition scanning so we can mount the first
        # partition if the image contains a partition table. Fall back to direct
        # loop mount if losetup is not available or partition node not found.
        if shutil.which("losetup"):
            try:
                loop = (
                    subprocess.run(
                        ["losetup", "-f", "--show", "-P", config.DATA_IMAGE],
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    .stdout.strip()
                )
            except Exception:
                loop = None

            if loop:
                # partition node can be /dev/loopXp1 or /dev/loopX1
                part1 = loop + \
                    "p1" if os.path.exists(loop + "p1") else loop + "1"

                # wait briefly for partition node
                for _ in range(20):
                    if os.path.exists(part1):
                        break
                    time.sleep(0.05)

                if os.path.exists(part1):
                    subprocess.run(
                        ["mount", part1, config.DATA_DIR], check=False)
                    return
                else:
                    # fall back to mounting the image directly
                    subprocess.run(
                        ["mount", "-o", "loop", config.DATA_IMAGE, config.DATA_DIR], check=False)
                    return

        # fallback when losetup not present
        subprocess.run(["mount", "-o", "loop", config.DATA_IMAGE,
                       config.DATA_DIR], check=False)

    @staticmethod
    def mount_ro():
        os.makedirs(config.DATA_DIR, exist_ok=True)
        # Similar to mount(), but prefer read-only mounts to avoid write conflicts.
        if shutil.which("losetup"):
            try:
                loop = (
                    subprocess.run(
                        ["losetup", "-f", "--show", "-P", config.DATA_IMAGE],
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    .stdout.strip()
                )
            except Exception:
                loop = None

            if loop:
                part1 = loop + \
                    "p1" if os.path.exists(loop + "p1") else loop + "1"

                for _ in range(20):
                    if os.path.exists(part1):
                        break
                    time.sleep(0.05)

                if os.path.exists(part1):
                    subprocess.run(["mount", "-o", "ro", part1,
                                   config.DATA_DIR], check=False)
                    return
                else:
                    subprocess.run(
                        ["mount", "-o", "ro,loop", config.DATA_IMAGE, config.DATA_DIR], check=False)
                    return

        subprocess.run(["mount", "-o", "ro,loop",
                       config.DATA_IMAGE, config.DATA_DIR], check=False)

    @staticmethod
    def umount():
        # try to unmount the filesystem
        subprocess.run(["umount", config.DATA_DIR], check=False)

        # ensure any loop device backing the image is detached.
        # losetup -j <file> prints matching loop devices like: /dev/loop0: [..]: /path/to/file
        try:
            if shutil.which("losetup"):
                p = subprocess.run(
                    ["losetup", "-j", config.DATA_IMAGE], capture_output=True, text=True)
                out = p.stdout.strip()
                for line in out.splitlines():
                    # extract device path up to the colon
                    dev = line.split(":", 1)[0].strip()
                    if dev:
                        subprocess.run(["losetup", "-d", dev], check=False)
        except Exception:
            # best-effort only
            pass

        # small delay to let kernel settle device nodes
        time.sleep(0.05)

    @staticmethod
    def is_mounted():
        os.makedirs(config.DATA_DIR, exist_ok=True)
        result = subprocess.run(
            ["mountpoint", "-q", config.DATA_DIR], check=False
        )
        return result.returncode == 0

    @staticmethod
    def bump_fat_volume_metadata():
        """
        Best-effort: tweak FAT volume metadata to encourage host re-cache.
        - Prefer setting a new FAT volume serial via mtools 'mlabel -N' if available.
        - Otherwise, update the volume label via fatlabel/dosfslabel.
        Works on the partition node if present (/dev/loopXp1 or /dev/loopX1),
        falling back to the whole loop device. No-op on failure.
        """
        # Requires losetup to address partitioned images cleanly.
        if not shutil.which("losetup"):
            return

        try:
            loop = (
                subprocess.run(
                    ["losetup", "-f", "--show", "-P", config.DATA_IMAGE],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip()
            )
        except Exception:
            return

        try:
            part1 = loop + "p1" if os.path.exists(loop + "p1") else loop + "1"
            dev = part1 if os.path.exists(part1) else loop

            # Prefer changing the volume label first (works well on Windows)
            tried = False
            if shutil.which("fatlabel"):
                try:
                    label = f"RECEIVE{int(time.time()) % 100000:05d}"
                    subprocess.run(["fatlabel", dev, label], check=False,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    tried = True
                except Exception:
                    pass

            if not tried and shutil.which("dosfslabel"):
                try:
                    label = f"RECEIVE{int(time.time()) % 100000:05d}"
                    subprocess.run(["dosfslabel", dev, label], check=False,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    tried = True
                except Exception:
                    pass

            # As a last resort, try setting a new FAT serial via mtools
            if not tried and shutil.which("mlabel"):
                try:
                    serial = f"{int(time.time() * 1000) & 0xFFFFFFFF:08X}"
                    subprocess.run(["mlabel", "-i", dev, "-N", serial, "::"], check=False,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
        finally:
            try:
                subprocess.run(["losetup", "-d", loop], check=False)
            except Exception:
                pass
