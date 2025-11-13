# ReceiveIt Server

Server running on a Raspberry Pi Zero 2 W to receive files over network and present them as a mass storage usb device to the host computer.

Device needs to use network and bluetooth for app functionality, so shell access needs to be enabled via usb serial interface. Since g_mass_storage and g_serial are mutually exclusive, it is required to use libcomposite/configfs to manage serial + mass storage.

# Requirements

Packages (_List is probably not exhaustive_):
- hostapd
- dnsmasq
- bluez
- xxd
