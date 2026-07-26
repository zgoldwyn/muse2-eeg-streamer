#include <stdio.h>
#include <strings.h>
#include "../include/muse2_constants.h"
#include "../include/muse2_decode.h"

void muse2_c_on_connected(const char *device_name){
    if (device_name == NULL) {
        printf("Connected to unknown device.\n");
        return;
    }
    printf("Connected to device: %s\n", device_name);
}

void muse2_c_on_service_discovered(const char *uuid){
    if (uuid == NULL) {
        printf("Discovered service with NULL UUID.\n");
        return;
    }
    printf("Discovered service: %s\n", uuid);
}

void muse2_c_on_characteristic_discovered(const char *service_uuid, const char *characteristic_uuid){
    if (service_uuid == NULL || characteristic_uuid == NULL) {
        printf("Discovered characteristic with NULL UUID input.\n");
        return;
    }
    printf("Discovered characteristic: %s in service: %s\n", characteristic_uuid, service_uuid);
    
    if (strcasecmp(characteristic_uuid, CONTROL) == 0) {
        printf("Found CONTROL characteristic, ready for command writes.\n");
    }
    else if (strcasecmp(characteristic_uuid, TP9) == 0) {
        printf("Found TP9 EEG characteristic, ready to subscribe.\n");
    }
    else if (strcasecmp(characteristic_uuid, AF7) == 0) {
        printf("Found AF7 EEG characteristic, ready to subscribe.\n");
    }
    else if (strcasecmp(characteristic_uuid, AF8) == 0) {
        printf("Found AF8 EEG characteristic, ready to subscribe.\n");
    }
    else if (strcasecmp(characteristic_uuid, TP10) == 0) {
        printf("Found TP10 EEG characteristic, ready to subscribe.\n");
    }
    else if (strcasecmp(characteristic_uuid, AUX) == 0) {
        printf("Found AUX EEG characteristic, ready to subscribe.\n");
    }

    

}
void muse2_c_on_eeg_packet(const char *characteristic_uuid, const unsigned char *bytes, unsigned long length) {
    if (characteristic_uuid == NULL || bytes == NULL) {
        printf("Received EEG packet with NULL input.\n");
        return;
    }
    if (length != MUSE2_EEG_PACKET_SIZE_BYTES) {
        printf("Received EEG packet with unexpected length: %lu bytes\n", length);
        return;
    }
    const char *buf = NULL;
    if (strcasecmp(characteristic_uuid, TP9) == 0) {
        buf = "TP9";
    }
    else if (strcasecmp(characteristic_uuid, AF7) == 0) {
        buf = "AF7";
    }
    else if (strcasecmp(characteristic_uuid, AF8) == 0) {
        buf = "AF8";
    }
    else if (strcasecmp(characteristic_uuid, TP10) == 0) {
        buf = "TP10";
    }
    else if (strcasecmp(characteristic_uuid, AUX) == 0) {
        buf = "AUX";
    }
    if (buf == NULL) {
        printf("Received EEG packet from unknown characteristic: %s\n", characteristic_uuid);
        return;
    }
    printf("C EVENT: Valid EEG packet of type %s from %s length=%lu\n", buf, characteristic_uuid, length);
    Muse2EegPacket out;
    if (muse2_decode_eeg_packet(bytes, length, &out) != 0) {
        printf("Failed to decode EEG packet from %s\n", characteristic_uuid);
        return;
    }
    printf("Decoded EEG packet: index=%u, raw[0]=%u, microvolts[0]=%.2f\n", out.packet_index, out.raw[0], out.microvolts[0]);
    printf("EEG,%s,%u,%.4f\n",buf,out.packet_index,out.microvolts[0]);  
}

