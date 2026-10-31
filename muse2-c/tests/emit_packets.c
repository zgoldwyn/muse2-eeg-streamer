// Sends known packets through the real muse2_c_on_eeg_packet, without a headset.
// tests/test_eeg_packet_output.py runs this and reads its output through a pipe.
// After the last packet it waits on stdin, so the test can prove the lines
// arrived while the program was still running, not when it exited and flushed.
#include <stdint.h>
#include <stdio.h>
#include "../include/muse2_constants.h"
#include "../include/muse2_events.h"

#define TEST_RECEIPT_NS 1234567890123ULL

int main(void) {
    // Same real packet as test_decode.c (index 93).
    const uint8_t real_packet[MUSE2_EEG_PACKET_SIZE_BYTES + 1] = {
        0x00, 0x5d,
        0x82, 0xc6, 0x45,
        0x6c, 0x98, 0xc3,
        0x8b, 0xa6, 0xc8,
        0x67, 0x08, 0x51,
        0x92, 0x47, 0x3f,
        0x63, 0xf7, 0xef
    };
    // Largest index, with samples alternating between the lowest and highest raw values.
    const uint8_t extreme_packet[MUSE2_EEG_PACKET_SIZE_BYTES] = {
        0xff, 0xff,
        0x00, 0x0f, 0xff,
        0x00, 0x0f, 0xff,
        0x00, 0x0f, 0xff,
        0x00, 0x0f, 0xff,
        0x00, 0x0f, 0xff,
        0x00, 0x0f, 0xff
    };

    // None of these should produce an EEG_PACKET line.
    muse2_c_on_eeg_packet(TP9, real_packet, MUSE2_EEG_PACKET_SIZE_BYTES - 1, TEST_RECEIPT_NS);
    muse2_c_on_eeg_packet(TP9, real_packet, MUSE2_EEG_PACKET_SIZE_BYTES + 1, TEST_RECEIPT_NS);
    muse2_c_on_eeg_packet(TP9, NULL, MUSE2_EEG_PACKET_SIZE_BYTES, TEST_RECEIPT_NS);
    muse2_c_on_eeg_packet(CONTROL, real_packet, MUSE2_EEG_PACKET_SIZE_BYTES, TEST_RECEIPT_NS);
    muse2_c_on_eeg_packet(AUX, real_packet, MUSE2_EEG_PACKET_SIZE_BYTES, TEST_RECEIPT_NS);

    muse2_c_on_eeg_packet(TP9, real_packet, MUSE2_EEG_PACKET_SIZE_BYTES, TEST_RECEIPT_NS);
    muse2_c_on_eeg_packet(AF7, real_packet, MUSE2_EEG_PACKET_SIZE_BYTES, TEST_RECEIPT_NS);
    muse2_c_on_eeg_packet(AF8, real_packet, MUSE2_EEG_PACKET_SIZE_BYTES, TEST_RECEIPT_NS);
    muse2_c_on_eeg_packet(TP10, extreme_packet, MUSE2_EEG_PACKET_SIZE_BYTES, TEST_RECEIPT_NS);

    getchar();
    return 0;
}
