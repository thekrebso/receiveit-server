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
        subprocess.run(
            ["mount", "-o", "loop", config.DATA_IMAGE, config.DATA_DIR], check=False
        )

    @staticmethod
    def umount():
        subprocess.run(["umount", config.DATA_DIR], check=False)

    @staticmethod
    def is_mounted():
        os.makedirs(config.DATA_DIR, exist_ok=True)
        result = subprocess.run(
            ["mountpoint", "-q", config.DATA_DIR], check=False
        )
        return result.returncode == 0
