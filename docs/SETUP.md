# Setting up the base station, a Wi-Fi dongle and the integration

This guide gets a REHAU Nea Smart 2.0 base station talking to Home Assistant
over a dedicated USB Wi-Fi dongle. It follows rehau-bridge's
[beginner guide](https://github.com/manuxio/rehau-nea-smart-2-home-assistant/blob/main/INSTALL.md),
which this integration originated from, with the MQTT add-on replaced by this
integration.

## What changes

The base station is switched into **access-point (AP) mode**: it opens its own
Wi-Fi network and serves a web interface at `http://192.168.0.2`. Home Assistant
joins that network with a second Wi-Fi adapter and reads the web interface.

- **The REHAU app and cloud stop working** while the base station is in AP mode.
  You can't use both.
- **The base station's Ethernet port is off in AP mode** (per rehau-bridge's
  guide). Wi-Fi is the only way in.
- Nothing else on your network can reach the base station. Only the Home
  Assistant host is on its Wi-Fi, which is intended.
- The base station has no internet access, so REHAU can't update its firmware.

## What you need

- The base station, powered and installed.
- Home Assistant 2026.11 or newer with [HACS](https://hacs.xyz).
- A USB Wi-Fi adapter that works under Linux. rehau-bridge recommends
  Realtek RTL8188/RTL8192 sticks. A **USB extension cable** is worth having,
  see [step 4](#4-check-the-signal).
- The Wi-Fi key of the base station: it is printed on the label under the
  base station and on a sticker on the front of its manual.
- The **installer code**, if you want calibration offsets, inputs/outputs and
  installer settings. See [step 5](#5-find-the-installer-code).

## 1. Put the base station in AP mode

At the base station (sequence from REHAU's manual, chapter 08.03 "Operating in
AP mode", as described by rehau-bridge):

1. Hold **OK + AP** for about 3 seconds, until the WLAN and AP LEDs blink.
2. Press **OK** to confirm. Both LEDs now stay on.
3. The base station opens a Wi-Fi network named like `NEASMART2-XX-XXX`.

To go back to the REHAU app later, leave AP mode with the same sequence. The
integration then stops working.

## 2. Connect the dongle to the base station's Wi-Fi

Give the dongle a **static address and no gateway**. The base station runs a
DHCP server that offers itself as the default gateway. If the dongle accepts it,
Home Assistant may send internet traffic to the base station, which has no
internet, and your other integrations stop working.

| Setting | Value |
|---|---|
| IPv4 | static / manual |
| Address | `192.168.0.10/24` (netmask `255.255.255.0`) |
| Gateway | empty |
| DNS | empty |
| IPv6 | disabled |

### Home Assistant OS

1. Shut Home Assistant down, plug in the dongle, start it again.
2. **Settings → System → Network**: there is a second Wi-Fi adapter now
   (often `wlan1`). If not, reboot once; if it's still missing, the dongle isn't
   supported.
3. Open that adapter, search for Wi-Fi networks, pick `NEASMART2-…` and enter
   the key.
4. Set IPv4 to **static** with the values above, leave gateway and DNS empty,
   and save.

### Home Assistant Container or Core on Linux

Configure the dongle on the host. With NetworkManager:

```bash
nmcli device                       # find the dongle, e.g. wlan1 or wlx…
nmcli connection add type wifi ifname <dongle> con-name neasmart \
  ssid <NEASMART2-…> wifi-sec.key-mgmt wpa-psk wifi-sec.psk '<key>' \
  ipv4.method manual ipv4.addresses 192.168.0.10/24 \
  ipv4.never-default yes ipv4.ignore-auto-dns yes ipv6.method disabled
nmcli connection up neasmart
```

A Home Assistant container needs `network_mode: host` (or another way to route
to `192.168.0.0/24`), since the base station is only reachable through the
host's dongle.

## 3. Check the link

- The base station's WLAN LED stays on without blinking once the dongle is
  connected.
- Home Assistant still loads and your cloud integrations still work. If not, a
  gateway or DNS server was set on the dongle; remove it.
- From the host (or the *Terminal & SSH* add-on), `ping 192.168.0.2` answers.

If your home network itself uses `192.168.0.x`, the two networks collide.
Change one of them.

## 4. Check the signal

The base station resends a lost packet only after about 2 seconds, and a
request waits that long. On the install this integration was built on, the dongle
saw **−66 dBm with 2–5 % packet loss**, so a few percent of requests took 2 s
longer. The integration shows changes immediately and confirms them in the
background, so switches don't lag, but a better link still helps:

- Put the dongle on a USB extension cable and move it closer to the base
  station, away from the host and other USB 3 devices.
- Check the signal and loss on Linux with `iw dev <dongle> link` and
  `ping -c 100 192.168.0.2`. Aim for no loss.

## 5. Find the installer code

The integration uses the installer code to switch the base station into
**installer mode**, which unlocks calibration offsets, inputs/outputs and the
installer settings pages. Without the code the integration still controls every
room.

- rehau-bridge describes the code as the first 8 characters of the serial number
  on the label under the base station (also shown as the *Unique code*).
- On the unit this integration was developed on, that was **not** the code. The
  real code was 10 characters long. If the first 8 characters don't unlock the
  installer pages in the base station's own web interface, ask your heating
  installer for the code.
- The base station answers a right and a wrong code the same way, so the setup
  can't tell you whether the code is right.

Installer mode is global: while the integration runs, it keeps installer mode
on, as rehau-bridge did, and turns it off when it is unloaded or Home Assistant
stops. You don't switch the base station into installer mode yourself.

## 6. Install the integration

1. Stop rehau-bridge or anything else polling the base station. It serves one
   client at a time. If you used rehau-bridge, also clear its retained MQTT
   discovery topics (`homeassistant/<domain>/rehau_*/config`), or its entities
   come back.
2. In HACS, add `https://github.com/cedrickring/rehau_neasmart` as a custom
   repository of type *Integration*, install **REHAU Nea Smart 2.0** and restart
   Home Assistant.
3. **Settings → Devices & services → Add integration → REHAU Nea Smart 2.0**.
   Enter host `192.168.0.2` and, optionally, the installer code.

The base station appears as a device with one child device per room. The I/O
entities start disabled; enable the ones you need. The options let you turn
the I/O polling off and the calibration offsets on.

## Troubleshooting

| Problem | Fix |
|---|---|
| Home Assistant lost internet after step 2 | The dongle got a gateway or DNS server. Remove them. |
| *Cannot connect* during setup | `ping 192.168.0.2` from the host. If it fails, the dongle isn't on the base station's Wi-Fi. In a container, check host networking. |
| Timeouts, entities flapping to unavailable | Another client is polling the base station (rehau-bridge, a browser tab on its web interface), or the signal is weak (step 4). |
| Rooms appear, installer entities don't | No installer code configured, or the calibration option is off. |
| Want the REHAU app back | Leave AP mode at the base station; remove the integration. |
