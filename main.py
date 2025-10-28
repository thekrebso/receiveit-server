#!/usr/bin/python3

from flask import Flask, request
import os
import shutil
import subprocess
import config
import usbimage


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
    with usbimage.USBImage():
        for filename in os.listdir(config.UPLOAD_DIR):
            src_path = os.path.join(config.UPLOAD_DIR, filename)
            dst_path = os.path.join(config.DATA_DIR, filename)
            shutil.copy2(src_path, dst_path)
            os.remove(src_path)

    return "OK\n"


@app.route("/reload", methods=["POST"])
def reload():
    usbimage.USBImage.usb_detach()
    usbimage.USBImage.usb_attach()
    return "OK\n"


@app.route("/clear", methods=["POST"])
def clear():
    with usbimage.USBImage():
        for name in os.listdir(config.DATA_DIR):
            path = os.path.join(config.DATA_DIR, name)
            try:
                if os.path.islink(path) or os.path.isfile(path):
                    os.remove(path)
                elif os.path.isdir(path):
                    shutil.rmtree(path)
            except Exception:
                # ignore/remove failures; consider logging if needed
                pass

    return "OK\n"


@app.route("/", methods=["GET"])
def index():
    return "Upload Server is running.\n"


if __name__ == "__main__":
    if not usbimage.USBImage.image_exists():
        usbimage.USBImage.image_create()

    if usbimage.USBImage.is_mounted():
        usbimage.USBImage.umount()
        usbimage.USBImage.usb_attach()

    if not usbimage.USBImage.is_usb_attached():
        usbimage.USBImage.usb_attach()

    app.run(host="0.0.0.0", port=80)
