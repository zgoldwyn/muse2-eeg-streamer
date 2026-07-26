void muse2_c_on_connected(const char *device_name);
void muse2_c_on_service_discovered(const char *uuid);
void muse2_c_on_characteristic_discovered(
    const char *service_uuid,
    const char *characteristic_uuid
);
void muse2_c_on_eeg_packet(const char *characteristic_uuid, const unsigned char *bytes, unsigned long length);