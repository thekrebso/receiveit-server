#!/usr/bin/python3

import time
from flask import Flask, request
import os
import shutil
import subprocess
import config
from USBGadget import USBGadget
from USBStorage import USBStorage


app = Flask("ReceiveIt")


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

    # reattach media without touching serial
    if USBGadget.is_initialized():
        USBGadget.replace_mass_storage_image(config.DATA_IMAGE)
    else:
        USBGadget.init()

    return "OK\n"


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
