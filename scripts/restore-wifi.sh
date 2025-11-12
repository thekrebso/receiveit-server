#!/bin/bash

systemctl stop receiveit-server.service 2>/dev/null || true
systemctl stop receiveit-ap.service 2>/dev/null || true
systemctl start NetworkManager 2>/dev/null || true
