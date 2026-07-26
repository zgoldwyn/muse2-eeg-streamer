

#ifndef MUSE2_BLE_H
#define MUSE2_BLE_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * C hooks called by the Objective-C CoreBluetooth bridge.
 *
 * The Objective-C file owns BLE scanning, connecting, subscribing, and raw
 * CoreBluetooth callbacks. C owns interpretation of events, packet validation,
 * decoding, buffering, and higher-level project behavior.
 */

void muse2_c_on_connected(const char *device_name);

void muse2_c_on_service_discovered(const char *service_uuid);

void muse2_c_on_characteristic_discovered(
    const char *service_uuid,
    const char *characteristic_uuid);

void muse2_c_on_eeg_packet(
    const char *characteristic_uuid,
    const unsigned char *bytes,
    unsigned long length);

#ifdef __cplusplus
}
#endif

#endif /* MUSE2_BLE_H */