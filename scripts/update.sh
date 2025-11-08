#!/bin/bash

cd /home/receiveit/receiveit-server || exit 1
./scripts/restore-wifi.sh
sleep 3

git pull
./scripts/update-files.sh
