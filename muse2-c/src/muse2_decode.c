#include "../include/muse2_decode.h"
#include "../include/muse2_constants.h"
#include <stdint.h>

/*
 * Decodes one 20-byte Muse 2 EEG notification packet.
 *
 * Preconditions:
 * - bytes points to at least len bytes.
 * - out points to valid writable memory.
 * - len must be >= MUSE2_EEG_PACKET_SIZE_BYTES.
 *
 * Returns:
 * - 0 on success
 * - nonzero on invalid input
 *
 * Safety:
 * - Does not allocate memory.
 * - Does not read beyond the first 20 bytes.
 * - Does not access hardware.
 */
int muse2_decode_eeg_packet(const uint8_t *bytes, size_t len, Muse2EegPacket *out){
    if (bytes == NULL || out == NULL) {
        return -1; // Null pointer error
    }
    if (len < MUSE2_EEG_PACKET_SIZE_BYTES) {
        return -1; // Not enough data
    }
    //big endian order:
    out->packet_index = ((uint16_t)bytes[0] << 8) | bytes[1];// Decode packet index (packet_index = first_byte * 256 + second_byte)
    

    /*ex: 
    packet_index = 0x01 0x02
    packet_index = 0x0102
    packet_index = 0x0100 | 0x0002 = 0x0102
    */

    const uint8_t *p = bytes + 2;

    for (int i = 0; i < MUSE2_EEG_SAMPLES_PER_PACKET; i += 2) {// Each sample is 12 bits, so we process two samples at a time (24 bits = 3 bytes)
        //ex aaaaaaaa bbbbcccc dddddddd  (where sample 1 is A and B and sample 2 is C and D)
        uint8_t b0 = p[0];
        uint8_t b1 = p[1];
        uint8_t b2 = p[2];

        uint16_t sample0 = ((uint16_t)b0 << 4) | (b1 >> 4);
        uint16_t sample1 = (((uint16_t)b1 & 0x0F) << 8) | b2;// Decode two 12-bit samples from three bytes

        out->raw[i] = sample0;
        out->raw[i + 1] = sample1;

        out->microvolts[i] =
            ((float)sample0 - MUSE2_ADC_CENTER) * MUSE2_SCALE_MICROVOLTS;

        out->microvolts[i + 1] =
            ((float)sample1 - MUSE2_ADC_CENTER) * MUSE2_SCALE_MICROVOLTS;// Convert raw samples to microvolts

        p += 3;
    }
    
    return 0; // Success
}