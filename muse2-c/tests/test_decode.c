#include <stdio.h>
#include <stdint.h>
#include "../include/muse2_decode.h"
#include "../include/muse2_constants.h"

static int test_real_packet(void) {
    uint8_t packet[MUSE2_EEG_PACKET_SIZE_BYTES] = {
        0x00, 0x5d,
        0x82, 0xc6, 0x45,
        0x6c, 0x98, 0xc3,
        0x8b, 0xa6, 0xc8,
        0x67, 0x08, 0x51,
        0x92, 0x47, 0x3f,
        0x63, 0xf7, 0xef
    };

    Muse2EegPacket decoded;

    int result = muse2_decode_eeg_packet(
        packet,
        MUSE2_EEG_PACKET_SIZE_BYTES,
        &decoded
    );

    if (result != 0) {
        printf("FAIL: real packet decode returned %d\n", result);
        return 1;
    }

    if (decoded.packet_index != 93) {
        printf("FAIL: expected packet index 93, got %u\n", decoded.packet_index);
        return 1;
    }

    if (decoded.raw[0] != 2092) {
        printf("FAIL: expected raw[0] = 2092, got %u\n", decoded.raw[0]);
        return 1;
    }

    if (decoded.raw[1] != 1605) {
        printf("FAIL: expected raw[1] = 1605, got %u\n", decoded.raw[1]);
        return 1;
    }

    printf("PASS: real Muse 2 packet decoded correctly\n");
    return 0;
}

static int test_short_packet_rejected(void) {
    uint8_t packet[MUSE2_EEG_PACKET_SIZE_BYTES - 1] = {0};
    Muse2EegPacket decoded;

    int result = muse2_decode_eeg_packet(
        packet,
        MUSE2_EEG_PACKET_SIZE_BYTES - 1,
        &decoded
    );

    if (result == 0) {
        printf("FAIL: short packet was accepted\n");
        return 1;
    }

    printf("PASS: short packet rejected with error %d\n", result);
    return 0;
}

static int test_null_bytes_rejected(void) {
    Muse2EegPacket decoded;

    int result = muse2_decode_eeg_packet(
        NULL,
        MUSE2_EEG_PACKET_SIZE_BYTES,
        &decoded
    );

    if (result == 0) {
        printf("FAIL: NULL bytes pointer was accepted\n");
        return 1;
    }

    printf("PASS: NULL bytes pointer rejected with error %d\n", result);
    return 0;
}

static int test_null_output_rejected(void) {
    uint8_t packet[MUSE2_EEG_PACKET_SIZE_BYTES] = {0};

    int result = muse2_decode_eeg_packet(
        packet,
        MUSE2_EEG_PACKET_SIZE_BYTES,
        NULL
    );

    if (result == 0) {
        printf("FAIL: NULL output pointer was accepted\n");
        return 1;
    }

    printf("PASS: NULL output pointer rejected with error %d\n", result);
    return 0;
}

int main(void) {
    int failures = 0;

    failures += test_real_packet();
    failures += test_short_packet_rejected();
    failures += test_null_bytes_rejected();
    failures += test_null_output_rejected();

    if (failures != 0) {
        printf("FAILED: %d test(s) failed\n", failures);
        return 1;
    }

    printf("ALL TESTS PASSED\n");
    return 0;
}