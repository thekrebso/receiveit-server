#!/bin/bash

systemctl stop p2p-autoconnect.path
systemctl stop p2p-autoconnect.service
systemctl stop p2p-events.path
systemctl stop p2p-events.service
systemctl stop p2p-ifwatch.service
systemctl stop p2p-find.service
systemctl stop p2p-wpa.service
systemctl start NetworkManager
