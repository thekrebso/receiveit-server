import os
import subprocess
import config


class USBImage:
    @staticmethod
    def image_create():
        if not os.path.exists(config.DATA_IMAGE):
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
            subprocess.run(
                ["mkfs.vfat", config.DATA_IMAGE],
                check=True,
            )

    @staticmethod
    def image_delete():
        if os.path.exists(config.DATA_IMAGE):
            os.remove(config.DATA_IMAGE)

    @staticmethod
    def image_exists():
        return os.path.exists(config.DATA_IMAGE)

    @staticmethod
    def mount():
        subprocess.run(
            ["mount", "-o", "loop", config.DATA_IMAGE, config.DATA_DIR], check=False
        )

    @staticmethod
    def umount():
        subprocess.run(["umount", config.DATA_DIR], check=False)

    @staticmethod
    def is_mounted():
        result = subprocess.run(
            ["mountpoint", "-q", config.DATA_DIR], check=False
        )
        return result.returncode == 0

    @staticmethod
    def usb_attach():
        subprocess.run(
            [
                "modprobe",
                "g_mass_storage",
                f"file={os.path.abspath(config.DATA_IMAGE)}",
                "removable=1",
                "ro=0",
            ],
            check=False,
        )

    @staticmethod
    def usb_detach():
        subprocess.run(["modprobe", "-r",
                       "g_mass_storage"], check=False)

    @staticmethod
    def is_usb_attached():
        result = subprocess.run(
            ["lsmod"], capture_output=True, text=True, check=False
        )
        return "g_mass_storage" in result.stdout

    def __enter__(self):
        self.usb_detach()
        self.mount()

    def __exit__(self, exc_type, exc_value, traceback):
        self.umount()
        self.usb_attach()
        return False
