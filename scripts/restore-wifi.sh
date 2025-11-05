#!/bin/bash

sudo systemctl stop p2p-ifwatch
sudo systemctl stop p2p-find
sudo systemctl stop p2p-wpa
sudo systemctl start NetworkManager
