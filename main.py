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
    # detach only mass storage so serial (acm) remains active
    if USBGadget.is_initialized():
        USBGadget.remove_mass_storage()

    # ensure backing image exists
    USBStorage.image_create()

    # mount image and copy uploaded files into it
    os.makedirs(config.DATA_DIR, exist_ok=True)
    USBStorage.mount()
    try:
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

    # update mass storage backing image in gadget (re-add mass storage)
    if USBGadget.is_initialized():
        USBGadget.add_mass_storage()
    else:
        # gadget not previously initialized; create full gadget (includes serial + ms)
        USBGadget.init()
    return "OK\n"


@app.route("/reload", methods=["POST"])
def reload():
    # detach only mass storage so serial (acm) remains active
    if USBGadget.is_initialized():
        USBGadget.remove_mass_storage()

    # ensure backing image exists
    USBStorage.image_create()

    # re-add mass storage without touching serial
    if USBGadget.is_initialized():
        USBGadget.add_mass_storage()
    else:
        USBGadget.init()

    return "OK\n"


@app.route("/clear", methods=["POST"])
def clear():
    # only remove mass storage so serial remains available
    if USBGadget.is_initialized():
        USBGadget.remove_mass_storage()

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

    # re-add mass storage without touching serial
    if USBGadget.is_initialized():
        USBGadget.add_mass_storage()
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
