#!/bin/bash

systemctl stop p2p-ifwatch.service
systemctl stop p2p-find.service
systemctl stop p2p-wpa.service
systemctl start NetworkManager
