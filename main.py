#!/usr/bin/python3

import time
from flask import Flask, request, send_file, send_from_directory, after_this_request
import os
import shutil
import subprocess
import config
from USBGadget import USBGadget
from USBStorage import USBStorage


app = Flask("ReceiveIt")


def _manifest_path():
    return os.path.abspath(config.DELETE_MANIFEST)


def _is_safe_relpath(p: str) -> bool:
    if not p:
        return False
    # Normalize and ensure it's a relative path with no traversal
    n = os.path.normpath(p).strip().lstrip("./")
    if not n or n.startswith("/") or ".." in n.split(os.sep):
        return False
    return True


def load_pending_deletions() -> set[str]:
    try:
        mp = _manifest_path()
        if not os.path.exists(mp):
            return set()
        with open(mp, "r") as f:
            paths = set()
            for line in f:
                s = line.strip()
                if _is_safe_relpath(s):
                    paths.add(s)
            return paths
    except Exception:
        return set()


def save_pending_deletions(paths: set[str]) -> None:
    try:
        mp = _manifest_path()
        os.makedirs(os.path.dirname(mp), exist_ok=True)
        with open(mp, "w") as f:
            for p in sorted(paths):
                f.write(p + "\n")
    except Exception:
        pass


def add_pending_deletion(relpath: str) -> bool:
    if not _is_safe_relpath(relpath):
        return False
    paths = load_pending_deletions()
    paths.add(os.path.normpath(relpath).lstrip("./"))
    save_pending_deletions(paths)
    return True


def remove_pending_deletion(relpath: str) -> bool:
    if not _is_safe_relpath(relpath):
        return False
    paths = load_pending_deletions()
    normalized = os.path.normpath(relpath).lstrip("./")
    if normalized in paths:
        paths.remove(normalized)
        save_pending_deletions(paths)
        return True
    return False


def apply_pending_deletions(mount_root: str) -> None:
    paths = load_pending_deletions()
    if not paths:
        return
    for rel in list(paths):
        target = os.path.join(mount_root, rel)
        try:
            if os.path.islink(target) or os.path.isfile(target):
                os.remove(target)
            elif os.path.isdir(target):
                shutil.rmtree(target)
        except Exception:
            # best-effort; leave entry for future commit if deletion failed
            continue
        # deletion succeeded; remove from manifest
        paths.discard(rel)
    save_pending_deletions(paths)


@app.route("/delete", methods=["POST"])
def delete():
    # Delete from upload if present; otherwise mark for deletion from image
    relpath = request.form.get("path") or (request.json or {}).get("path")
    if not relpath or not _is_safe_relpath(relpath):
        return "Invalid path\n", 400
    relpath = os.path.normpath(relpath).lstrip("./")

    upload_target = os.path.join(config.UPLOAD_DIR, relpath)
    if os.path.exists(upload_target):
        try:
            if os.path.isfile(upload_target) or os.path.islink(upload_target):
                os.remove(upload_target)
            elif os.path.isdir(upload_target):
                shutil.rmtree(upload_target)
            return "OK\n"
        except Exception:
            return "Failed\n", 500

    # Not in upload; mark for deletion from committed image
    if add_pending_deletion(relpath):
        return "OK\n"
    return "Failed\n", 500


@app.route("/undelete", methods=["POST"])
def undelete():
    relpath = request.form.get("path") or (request.json or {}).get("path")
    if not relpath or not _is_safe_relpath(relpath):
        return "Invalid path\n", 400
    if remove_pending_deletion(relpath):
        return "OK\n"
    return "Not found\n", 404


@app.route("/upload", methods=["POST"])
def upload():
    os.makedirs(config.UPLOAD_DIR, exist_ok=True)
    files = request.files.getlist("file")

    for f in files:
        path = os.path.join(config.UPLOAD_DIR, f.filename)
        f.save(path)

    return "OK\n"


@app.route("/commit", methods=["POST"])
def commit():
    # If gadget is active, detach media first so the backing file isn't busy
    if USBGadget.is_initialized():
        USBGadget.detach_mass_storage_media()
        time.sleep(0.1)
    # ensure backing image exists
    USBStorage.image_create()

    # mount image and copy uploaded files into it
    os.makedirs(config.DATA_DIR, exist_ok=True)
    USBStorage.mount()
    try:
        apply_pending_deletions(config.DATA_DIR)

        if not os.path.isdir(config.UPLOAD_DIR):
            # nothing to commit
            pass
        else:
            for filename in os.listdir(config.UPLOAD_DIR):
                src_path = os.path.join(config.UPLOAD_DIR, filename)
                dst_path = os.path.join(config.DATA_DIR, filename)
                try:
                    if os.path.isdir(src_path):
                        # copy directory
                        if os.path.exists(dst_path):
                            shutil.rmtree(dst_path)
                        shutil.copytree(src_path, dst_path)
                    else:
                        shutil.copy2(src_path, dst_path)
                    os.remove(src_path)
                except Exception:
                    # ignore individual file errors
                    pass
    finally:
        USBStorage.umount()
        # ensure data is flushed to image
        try:
            os.sync()
        except Exception:
            try:
                subprocess.run(["sync"], check=False)
            except Exception:
                pass
        # tweak FAT volume metadata to prod Windows into re-caching
        try:
            USBStorage.bump_fat_volume_metadata()
        except Exception:
            pass

    # update mass storage media without touching serial function
    if USBGadget.is_initialized():
        USBGadget.replace_mass_storage_image(config.DATA_IMAGE)
    else:
        # gadget not previously initialized; create full gadget (includes serial + ms)
        USBGadget.init()
    return "OK\n"


@app.route("/reload", methods=["POST"])
def reload():
    # ensure backing image exists
    USBStorage.image_create()

    # swap media without touching serial
    if USBGadget.is_initialized():
        USBGadget.replace_mass_storage_image(config.DATA_IMAGE)
    else:
        USBGadget.init()

    return "OK\n"


@app.route("/clear", methods=["POST"])
def clear():
    # Detach media first if gadget is active
    if USBGadget.is_initialized():
        USBGadget.detach_mass_storage_media()
        time.sleep(0.1)

    USBStorage.image_create()
    USBStorage.mount()
    try:
        for name in os.listdir(config.DATA_DIR):
            path = os.path.join(config.DATA_DIR, name)
            try:
                if os.path.islink(path) or os.path.isfile(path):
                    os.remove(path)
                elif os.path.isdir(path):
                    shutil.rmtree(path)
            except Exception:
                pass
    finally:
        USBStorage.umount()
        try:
            os.sync()
        except Exception:
            try:
                subprocess.run(["sync"], check=False)
            except Exception:
                pass
        try:
            USBStorage.bump_fat_volume_metadata()
        except Exception:
            pass

    # reattach media without touching serial
    if USBGadget.is_initialized():
        USBGadget.replace_mass_storage_image(config.DATA_IMAGE)
    else:
        USBGadget.init()

    return "OK\n"


def list_files_in_image():
    # run fls -o 2048 data.img -u
    try:
        result = subprocess.run(
            ["fls", "-o", "2048", "-u", "-p", config.DATA_IMAGE],
            capture_output=True,
            text=True,
            check=True,
        )
        files = []
        for line in result.stdout.splitlines():
            if ":" not in line:
                continue
            pre, path = line.split(":", 1)
            pre = pre.strip()
            path = path.strip().strip('"')

            # Skip deleted entries (fls marks deleted with '*')
            if "*" in pre:
                continue

            # Only include regular files (type token starts with 'r')
            type_token = pre.split()[0] if pre.split() else ""
            if not type_token.startswith("r"):
                continue

            # Skip metadata and system entries in any path component
            if not path:
                continue
            components = [c for c in path.strip("/").split("/") if c]
            if any(c == "System Volume Information" for c in components):
                continue
            if any(c.startswith("$") for c in components):
                continue
            if any(c in {"$MBR", "$FAT1", "$FAT2", "$OrphanFiles"} for c in components):
                continue
            # Ignore common macOS metadata and resource fork files/directories
            if any(
                c in {
                    ".DS_Store",
                    ".Spotlight-V100",
                    ".fseventsd",
                    ".Trashes",
                    ".TemporaryItems",
                    ".AppleDouble",
                    ".VolumeIcon.icns",
                }
                for c in components
            ):
                continue
            # AppleDouble resource fork files alongside originals
            if any(c.startswith("._") for c in components):
                continue

            normalized = path.lstrip("/")
            if normalized:
                files.append(normalized)

        # Apply marker "*" for pending deletions
        pending = load_pending_deletions()
        marked = [("*" + f) if f in pending else f for f in files]
        print("Files in image:", marked)
        return marked
    except Exception:
        print("Failed to list files in image")
        return []


def list_files_in_upload():
    if not os.path.exists(config.UPLOAD_DIR):
        print("Upload directory does not exist")
        return []
    files = os.listdir(config.UPLOAD_DIR)
    # pending = load_pending_deletions()
    # marked = [("*" + f) if f in pending else f for f in files]
    # print("Files in upload:", marked)
    # return marked
    print("Files in upload:", files)
    return files


@app.route("/list", methods=["GET"])
def list_files():
    files_in_image = list_files_in_image()
    files_in_upload = list_files_in_upload()
    files = {"image": files_in_image, "upload": files_in_upload}
    print("Listing files:", files)
    return files


@app.route("/download", methods=["GET"])
def download():
    source = request.args.get("source", "").strip().lower()
    relpath = request.args.get("path", "")
    if not relpath or not _is_safe_relpath(relpath):
        return "Invalid path\n", 400
    relpath = os.path.normpath(relpath).lstrip("./")

    if source == "upload":
        # Serve directly from upload directory
        try:
            return send_from_directory(config.UPLOAD_DIR, relpath, as_attachment=True)
        except Exception:
            return "Not found\n", 404

    elif source == "image":
        # Ensure backing image exists
        USBStorage.image_create()

        # Mount read-only to avoid conflicts with active gadget
        mounted_here = False
        try:
            if not USBStorage.is_mounted():
                USBStorage.mount_ro()
                mounted_here = True

            abs_path = os.path.join(config.DATA_DIR, relpath)

            if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
                # If we mounted in this handler, unmount before returning
                if mounted_here:
                    USBStorage.umount()
                return "Not found\n", 404

            resp = send_file(abs_path, as_attachment=True)

            # Ensure we unmount after the response is fully sent
            if mounted_here:
                try:
                    resp.call_on_close(lambda: USBStorage.umount())
                except Exception:
                    # Fallback: schedule unmount best-effort after response creation
                    @after_this_request
                    def _cleanup(response):
                        try:
                            USBStorage.umount()
                        except Exception:
                            pass
                        return response
            return resp
        except Exception:
            # Best-effort cleanup if we mounted here
            try:
                if mounted_here:
                    USBStorage.umount()
            except Exception:
                pass
            return "Failed\n", 500

    else:
        return "Invalid source\n", 400


@app.route("/", methods=["GET"])
def index():
    return "Upload Server is running.\n"


if __name__ == "__main__":
    time.sleep(3)
    USBStorage.image_create()

    # try to initialize gadget early if configfs & UDC available. Non-fatal.
    try:
        if USBGadget.is_ready() and not USBGadget.is_initialized():
            try:
                USBGadget.init()
                print("USBGadget initialized at startup")
            except Exception as e:
                print("USBGadget init failed at startup:", e)
    except Exception:
        # ignore readiness checks failing on platforms without configfs
        pass

    app.run(host="0.0.0.0", port=80)
