#!/bin/bash

cd /home/receiveit/receiveit-server || exit 1
cp -r ./etc/systemd/system/* /etc/systemd/system/
cp ./etc/wpa_supplicant/* /etc/wpa_supplicant/
cp ./boot/firmware/* /boot/firmware/
