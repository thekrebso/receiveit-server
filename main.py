#!/usr/bin/python3

import time
from flask import Flask, request
import os
import shutil
import subprocess
import config
from USBGadget import USBGadget
from USBStorage import USBStorage
import threading
from typing import Dict, Tuple, List


app = Flask("ReceiveIt")


# Inode cache for fast directory listings
INODE_CACHE: Dict[str, int] = {}
INODE_CACHE_LOCK = threading.Lock()
INODE_CACHE_READY = False


def _normalize_path(path: str) -> str:
    if not path:
        return "/"
    p = path.strip()
    if not p.startswith("/"):
        p = "/" + p
    if len(p) > 1 and p.endswith("/"):
        p = p[:-1]
    return p


def _should_skip_components(components: List[str]) -> bool:
    if any(c == "System Volume Information" for c in components):
        return True
    if any(c.startswith("$") for c in components):
        return True
    if any(c in {"$MBR", "$FAT1", "$FAT2", "$OrphanFiles"} for c in components):
        return True
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
        return True
    if any(c.startswith("._") for c in components):
        return True
    return False


def build_inode_cache() -> None:
    global INODE_CACHE_READY
    # Build cache of directory path -> inode using recursive fls
    try:
        result = subprocess.run(
            [
                "fls",
                "-o",
                "2048",
                "-u",
                "-r",
                "-p",
                config.DATA_IMAGE,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        cache: Dict[str, int] = {}
        for line in result.stdout.splitlines():
            if ":" not in line:
                continue
            pre, path = line.split(":", 1)
            pre = pre.strip()
            path = path.strip().strip('"')

            # Skip deleted entries
            if "*" in pre:
                continue

            # Parse type and inode
            parts = pre.split()
            type_token = parts[0] if parts else ""
            inode = None
            for tok in reversed(parts):
                if tok.isdigit():
                    try:
                        inode = int(tok)
                        break
                    except Exception:
                        pass

            if not path:
                continue
            components = [c for c in path.strip("/").split("/") if c]
            if _should_skip_components(components):
                continue

            # Only cache directories
            if type_token.startswith("d") and inode is not None:
                normalized = _normalize_path(path)
                cache[normalized] = inode

        with INODE_CACHE_LOCK:
            INODE_CACHE.clear()
            # Ensure root has an entry if present
            if "/" not in cache:
                # Attempt to find root inode by listing root non-recursively
                try:
                    root = subprocess.run(
                        ["fls", "-o", "2048", "-u", config.DATA_IMAGE],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    for line in root.stdout.splitlines():
                        if ":" not in line:
                            continue
                        pre, _ = line.split(":", 1)
                        parts = pre.strip().split()
                        inode = None
                        for tok in reversed(parts):
                            if tok.isdigit():
                                inode = int(tok)
                                break
                        if inode is not None:
                            cache["/"] = inode
                            break
                except Exception:
                    pass
            INODE_CACHE.update(cache)
            INODE_CACHE_READY = True
        print(f"Inode cache built with {len(cache)} directories")
    except Exception as e:
        print("Failed to build inode cache:", e)


def start_cache_refresh_async() -> None:
    def _worker():
        try:
            build_inode_cache()
        except Exception:
            pass

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


def _list_dir_by_inode(inode: int) -> Tuple[List[str], List[str]]:
    # Fast list directory entries by inode — no recursion
    try:
        result = subprocess.run(
            ["fls", "-o", "2048", "-u", "-p", config.DATA_IMAGE, str(inode)],
            capture_output=True,
            text=True,
            check=True,
        )
        files: List[str] = []
        dirs: List[str] = []
        for line in result.stdout.splitlines():
            if ":" not in line:
                continue
            pre, path = line.split(":", 1)
            pre = pre.strip()
            path = path.strip().strip('"')

            if "*" in pre:
                continue

            parts = pre.split()
            type_token = parts[0] if parts else ""
            if not path:
                continue
            components = [c for c in path.strip("/").split("/") if c]
            if _should_skip_components(components):
                continue

            name = components[-1] if components else path
            if type_token.startswith("d"):
                dirs.append(name)
            elif type_token.startswith("r"):
                files.append(name)
        return files, dirs
    except Exception:
        return [], []


def list_entries_for_path(path: str) -> List[str]:
    # Returns single list of names for immediate children; directories end with '/'
    normalized = _normalize_path(path)
    # Root can be listed by path quickly
    if normalized == "/":
        # Use inode cache if available for fast listing
        with INODE_CACHE_LOCK:
            inode = INODE_CACHE.get("/")
        if inode is not None:
            files, dirs = _list_dir_by_inode(inode)
            return sorted([*(f for f in files), *(d + "/" for d in dirs)])
        # Fallback to direct non-recursive path listing if inode missing
        try:
            result = subprocess.run(
                ["fls", "-o", "2048", "-u", "-p", config.DATA_IMAGE],
                capture_output=True,
                text=True,
                check=True,
            )
            files: List[str] = []
            dirs: List[str] = []
            for line in result.stdout.splitlines():
                if ":" not in line:
                    continue
                pre, path_line = line.split(":", 1)
                pre = pre.strip()
                path_line = path_line.strip().strip('"')
                if "*" in pre:
                    continue
                parts = pre.split()
                type_token = parts[0] if parts else ""
                comps = [c for c in path_line.strip("/").split("/") if c]
                if _should_skip_components(comps):
                    continue
                name = comps[-1] if comps else path_line
                if type_token.startswith("d"):
                    dirs.append(name)
                elif type_token.startswith("r"):
                    files.append(name)
            return sorted([*(f for f in files), *(d + "/" for d in dirs)])
        except Exception:
            return []

    # Non-root: try cached inode first
    with INODE_CACHE_LOCK:
        inode = INODE_CACHE.get(normalized)
    if inode is None:
        # Cache miss — build synchronously (may take ~20s)
        build_inode_cache()
        with INODE_CACHE_LOCK:
            inode = INODE_CACHE.get(normalized)
        if inode is None:
            return []
    files, dirs = _list_dir_by_inode(inode)
    return sorted([*(f for f in files), *(d + "/" for d in dirs)])


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
    # Refresh inode cache asynchronously since contents changed
    try:
        start_cache_refresh_async()
    except Exception:
        pass
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

    # Refresh inode cache asynchronously since media was swapped
    try:
        start_cache_refresh_async()
    except Exception:
        pass
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

    # Refresh inode cache asynchronously after clear
    try:
        start_cache_refresh_async()
    except Exception:
        pass
    return "OK\n"


def list_files_in_image():
    # run fls -o 2048 data.img -u
    try:
        result = subprocess.run(
            ["fls", "-o", "2048", "-u", "-r", "-p", config.DATA_IMAGE],
            capture_output=True,
            text=True,
            check=True,
        )
        # Example output lines:
        # "5: System Volume Information","8: wallhaven-rregrm.png","133922819: $MBR","133922820: $FAT1","133922821: $FAT2","133922822: $OrphanFiles"
        # Ignore System Volume Information and metadata files
        # Extract filenames after the colon
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
        print("Files in image:", files)
        return files
    except Exception:
        print("Failed to list files in image")
        return []


def list_files_in_upload():
    if not os.path.exists(config.UPLOAD_DIR):
        print("Upload directory does not exist")
        return []
    files = os.listdir(config.UPLOAD_DIR)
    print("Files in upload:", files)
    return files


@app.route("/list", methods=["GET"])
def list_files():
    path = request.args.get("path", "/")
    image_entries = list_entries_for_path(path)
    upload_entries = list_files_in_upload()
    resp = {"image": image_entries, "upload": upload_entries}
    print("Listing files:", resp)
    return resp


@app.route("/", methods=["GET"])
def index():
    return "Upload Server is running.\n"


if __name__ == "__main__":
    time.sleep(3)
    USBStorage.image_create()

    # Build inode cache in background to avoid first-hit delay
    try:
        start_cache_refresh_async()
    except Exception:
        pass

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
