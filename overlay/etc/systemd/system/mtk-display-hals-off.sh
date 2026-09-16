#!/bin/sh
# Prepare the vendor display stack before Mir starts.
#
# Ubuntu Touch reaches hwcomposer over HIDL: the main thread of
# lomiri-system-compositor blocks in getService(IComposer@2.1) until the Android
# composer@2.1 service registers. That service can only register if it owns
# /dev/dri/card0, which means it has to open the node before the compositor
# does. On a normal boot lightdm starts first and takes the display, and then
# the two wait for each other.
#
# So: start the service, wait for it to register, and only then let lightdm run.
set -u
GETPROP=/system/bin/getprop
SETPROP=/system/bin/setprop
LSHAL=/system/bin/lshal
IFACE="android.hardware.graphics.composer@2.1::IComposer/default"

i=0
while [ $i -lt 60 ]; do
    [ -x "$GETPROP" ] && [ -n "$($GETPROP init.svc.servicemanager 2>/dev/null)" ] && break
    sleep 1; i=$((i+1))
done

"$SETPROP" ctl.start vendor.hwcomposer-2-1 2>/dev/null

i=0
while [ $i -lt 40 ]; do
    if "$LSHAL" 2>/dev/null | grep -q "$IFACE"; then
        exit 0
    fi
    sleep 1; i=$((i+1))
done
exit 0
