import os
import shutil
import time
import config
from USBStorage import USBStorage


class USBGadget:
    @staticmethod
    def _write(path, data):
        try:
            with open(path, "w") as f:
                f.write(str(data))
            return True
        except Exception:
            try:
                # best-effort logging to stdout (captured by systemd journal)
                import traceback
                print(f"USBGadget: failed to write {path} = {data}")
                traceback.print_exc()
            except Exception:
                pass
            return False

    @staticmethod
    def _read(path):
        try:
            with open(path, "r") as f:
                return f.read()
        except Exception:
            return None

    @staticmethod
    def _ensure_dir(path):
        try:
            os.makedirs(path, exist_ok=True)
            return True
        except Exception:
            try:
                import traceback
                print(f"USBGadget: failed to create directory {path}")
                traceback.print_exc()
            except Exception:
                pass
            return False

    @staticmethod
    def is_ready():
        """
        Returns True if configfs is available and at least one UDC is present.
        """
        if not os.path.isdir("/sys/kernel/config"):
            return False
        try:
            udcs = os.listdir("/sys/class/udc")
            return len(udcs) > 0
        except Exception:
            return False

    @staticmethod
    def is_initialized():
        """
        Returns True if the gadget path exists (i.e. gadget created).
        """
        return os.path.isdir(config.GADGET_PATH)

    @staticmethod
    def init():
        """
        Create and bind a composite gadget with ACM (serial) + mass_storage.
        """
        if not USBGadget.is_ready():
            raise RuntimeError("configfs or UDC not available")

        if USBGadget.is_initialized():
            # already created
            return

        # ensure backing file exists
        USBStorage.image_create()

        # basic gadget attributes
        USBGadget._ensure_dir(config.GADGET_PATH)
        USBGadget._write(os.path.join(
            config.GADGET_PATH, "idVendor"), "0x1d6b")
        USBGadget._write(os.path.join(
            config.GADGET_PATH, "idProduct"), "0x0104")
        USBGadget._write(os.path.join(
            config.GADGET_PATH, "bcdDevice"), "0x0100")
        USBGadget._write(os.path.join(config.GADGET_PATH, "bcdUSB"), "0x0200")

        # english strings
        strings = os.path.join(config.GADGET_PATH, "strings", "0x409")
        USBGadget._ensure_dir(strings)
        USBGadget._write(os.path.join(strings, "serialnumber"), "receiveit")
        USBGadget._write(os.path.join(strings, "manufacturer"), "receiveit")
        USBGadget._write(os.path.join(strings, "product"), "ReceiveIt")

        # configuration
        cfg = os.path.join(config.GADGET_PATH, "configs", "c.1")
        USBGadget._ensure_dir(cfg)
        USBGadget._write(os.path.join(cfg, "MaxPower"), "250")
        cfg_strings = os.path.join(cfg, "strings", "0x409")
        USBGadget._ensure_dir(cfg_strings)
        USBGadget._write(os.path.join(
            cfg_strings, "configuration"), "Config 1")

        # functions: acm (serial) and mass_storage
        funcs = os.path.join(config.GADGET_PATH, "functions")
        acm = os.path.join(funcs, "acm.usb0")
        ms = os.path.join(funcs, "mass_storage.0")
        USBGadget._ensure_dir(acm)
        USBGadget._ensure_dir(ms)

        # configure mass storage lun
        lun_file = os.path.join(ms, "lun.0", "file")
        # create lun.0 directory if required
        USBGadget._ensure_dir(os.path.join(ms, "lun.0"))
        USBGadget._write(lun_file, os.path.abspath(config.DATA_IMAGE))
        # optional: mark removable
        try:
            USBGadget._write(os.path.join(ms, "lun.0", "removable"), "1")
        except Exception:
            pass

        # link functions into config
        try:
            acm_link = os.path.join(cfg, "acm.usb0")
            ms_link = os.path.join(cfg, "mass_storage.0")
            if not os.path.exists(acm_link):
                os.symlink(acm, acm_link)
            if not os.path.exists(ms_link):
                os.symlink(ms, ms_link)
        except Exception:
            # best-effort linking; cleanup on failure below
            pass

        # bind gadget to first available UDC
        udc_list = os.listdir("/sys/class/udc")
        if not udc_list:
            raise RuntimeError("no UDC available to bind gadget")
        udc = udc_list[0]
        USBGadget._write(os.path.join(config.GADGET_PATH, "UDC"), udc)

        # diagnostic prints: show what got written/read back for vendor/product and UDC
        try:
            with open(os.path.join(config.GADGET_PATH, "idVendor"), "r") as f:
                v = f.read().strip()
            with open(os.path.join(config.GADGET_PATH, "idProduct"), "r") as f:
                p = f.read().strip()
            print(f"USBGadget: idVendor={v} idProduct={p} bound_UDC={udc}")
        except Exception:
            try:
                print("USBGadget: unable to read back idVendor/idProduct after init")
            except Exception:
                pass

        # allow some time for host to enumerate
        time.sleep(0.1)

    @staticmethod
    def deinit():
        """
        Unbind and remove the gadget from configfs.
        """
        if not USBGadget.is_initialized():
            return

        # unbind
        USBGadget._write(os.path.join(config.GADGET_PATH, "UDC"), "")

        # remove config links
        cfg = os.path.join(config.GADGET_PATH, "configs", "c.1")
        try:
            for name in os.listdir(cfg):
                path = os.path.join(cfg, name)
                try:
                    if os.path.islink(path):
                        os.unlink(path)
                except Exception:
                    pass
        except Exception:
            pass

        # remove functions
        funcs = os.path.join(config.GADGET_PATH, "functions")
        try:
            for fn in os.listdir(funcs):
                fnpath = os.path.join(funcs, fn)
                try:
                    shutil.rmtree(fnpath)
                except Exception:
                    # try simple remove
                    try:
                        os.rmdir(fnpath)
                    except Exception:
                        pass
        except Exception:
            pass

        # remove configs, strings and gadget dir
        try:
            shutil.rmtree(os.path.join(config.GADGET_PATH, "configs"))
        except Exception:
            pass
        try:
            shutil.rmtree(os.path.join(config.GADGET_PATH, "strings"))
        except Exception:
            pass

        try:
            shutil.rmtree(config.GADGET_PATH)
        except Exception:
            try:
                os.rmdir(config.GADGET_PATH)
            except Exception:
                pass

    @staticmethod
    def remove_mass_storage():
        """
        Remove mass_storage function from the active configuration (only unlink from config).
        This leaves other functions (e.g. acm.usb0) intact.
        """
        cfg = os.path.join(config.GADGET_PATH, "configs", "c.1")
        ms_link = os.path.join(cfg, "mass_storage.0")
        try:
            if os.path.islink(ms_link) or os.path.exists(ms_link):
                os.unlink(ms_link)
            return True
        except Exception:
            return False

    @staticmethod
    def add_mass_storage():
        """
        Ensure the mass_storage function exists, point its lun.0/file to the DATA_IMAGE and
        link it into the active config. Safe to call when gadget/config already exists.
        """
        funcs = os.path.join(config.GADGET_PATH, "functions")
        ms = os.path.join(funcs, "mass_storage.0")
        USBGadget._ensure_dir(ms)
        # ensure lun directory and set backing file
        USBGadget._ensure_dir(os.path.join(ms, "lun.0"))
        lun_file = os.path.join(ms, "lun.0", "file")
        # try a few times to write the lun file in case the kernel/configfs is briefly busy
        written = False
        for _ in range(5):
            if USBGadget._write(lun_file, os.path.abspath(config.DATA_IMAGE)):
                written = True
                break
            time.sleep(0.05)
        try:
            USBGadget._write(os.path.join(ms, "lun.0", "removable"), "1")
        except Exception:
            pass

        cfg = os.path.join(config.GADGET_PATH, "configs", "c.1")
        ms_link = os.path.join(cfg, "mass_storage.0")
        try:
            if not os.path.exists(ms_link):
                os.symlink(ms, ms_link)
                # small delay to allow host to notice the function (reduces race on re-enumeration)
                time.sleep(0.05)
            return written
        except Exception:
            return False

    @staticmethod
    def replace_mass_storage_image(new_image_path):
        """
        Replace mass storage backing image without unbinding the gadget or
        removing the function symlink. We "eject" by writing an empty string to
        the lun.0/file, then point it to the new image path. This triggers a
        media change on the host without dropping the CDC ACM interface.
        """
        if not USBGadget.is_initialized():
            # nothing to do — gadget not created
            return False
        try:
            # Ensure the mass_storage function exists and is linked
            USBGadget.add_mass_storage()

            funcs = os.path.join(config.GADGET_PATH, "functions")
            ms = os.path.join(funcs, "mass_storage.0")
            lun_dir = os.path.join(ms, "lun.0")
            USBGadget._ensure_dir(lun_dir)
            lun_file = os.path.join(lun_dir, "file")

            # Step 1: forcibly eject current media if supported, otherwise clear file
            detached = False
            forced_eject_path = os.path.join(lun_dir, "forced_eject")
            if os.path.exists(forced_eject_path):
                for _ in range(5):
                    if USBGadget._write(forced_eject_path, "1"):
                        detached = True
                        break
                    time.sleep(0.05)
            if not detached:
                for _ in range(10):
                    if USBGadget._write(lun_file, ""):
                        detached = True
                        break
                    time.sleep(0.05)

            # Give host a window to see media removal
            time.sleep(2)

            # Step 2: attach new image
            new_path = os.path.abspath(new_image_path)
            attached = False
            for _ in range(10):
                if USBGadget._write(lun_file, new_path):
                    attached = True
                    break
                time.sleep(0.1)

            # Optional: verify write by reading back
            if attached:
                cur = (USBGadget._read(lun_file) or "").strip()
                if cur != new_path:
                    attached = False

            # Nudge host
            time.sleep(2)

            # Fallback: if attach didn't stick, briefly unlink/relink function to force re-enum
            if not attached:
                cfg = os.path.join(config.GADGET_PATH, "configs", "c.1")
                ms_link = os.path.join(cfg, "mass_storage.0")
                try:
                    if os.path.islink(ms_link) or os.path.exists(ms_link):
                        os.unlink(ms_link)
                    time.sleep(0.1)
                except Exception:
                    pass
                # ensure file points to new image
                USBGadget._write(lun_file, new_path)
                try:
                    if not os.path.exists(ms_link):
                        os.symlink(ms, ms_link)
                        time.sleep(0.2)
                except Exception:
                    pass
                # final readback check
                cur2 = (USBGadget._read(lun_file) or "").strip()
                attached = (cur2 == new_path)

            return detached and attached
        except Exception:
            return False

    @staticmethod
    def detach_mass_storage_media():
        """
        Temporarily detach the mass storage media by clearing lun.0/file.
        Keeps the gadget and function active (e.g., ACM stays up), but the
        host will see the storage removed. Use before updating the image.
        """
        if not USBGadget.is_initialized():
            return False

        try:
            USBGadget.add_mass_storage()
            lun_dir = os.path.join(
                config.GADGET_PATH, "functions", "mass_storage.0", "lun.0"
            )
            lun_file = os.path.join(lun_dir, "file")
            forced_eject_path = os.path.join(lun_dir, "forced_eject")

            # Prefer forced_eject if supported
            if os.path.exists(forced_eject_path):
                for _ in range(5):
                    if USBGadget._write(forced_eject_path, "1"):
                        time.sleep(0.2)
                        return True
                    time.sleep(0.05)

            for _ in range(10):
                if USBGadget._write(lun_file, ""):
                    time.sleep(0.2)
                    return True
                time.sleep(0.05)
            return False
        except Exception:
            return False

    @staticmethod
    def attach_mass_storage_media(image_path):
        """
        Attach the given image to the mass storage LUN (writes path to
        lun.0/file). Triggers media insertion on the host.
        """
        if not USBGadget.is_initialized():
            return False

        try:
            USBGadget.add_mass_storage()
            lun_file = os.path.join(
                config.GADGET_PATH, "functions", "mass_storage.0", "lun.0", "file"
            )
            new_path = os.path.abspath(image_path)
            for _ in range(10):
                if USBGadget._write(lun_file, new_path):
                    time.sleep(0.1)
                    return True
                time.sleep(0.1)
            return False
        except Exception:
            return False
