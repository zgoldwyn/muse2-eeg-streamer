#include <stdint.h>
#include <stddef.h>
typedef struct {
    uint16_t packet_index;
    uint16_t raw[12];
    float microvolts[12];
} Muse2EegPacket;

int muse2_decode_eeg_packet(
    const uint8_t *bytes,
    size_t len,
    Muse2EegPacket *out
);