// Thin Objective-C/CoreBluetooth adapter for Muse 2 BLE access.
// Packet decoding, validation, buffering, and project logic belong in C.

#import <Foundation/Foundation.h>
#import <CoreBluetooth/CoreBluetooth.h>

#import "muse2_ble.h"


#pragma mark - Muse UUIDs

static NSString *const MUSE2_CONTROL_UUID =
    @"273E0001-4C4D-454D-96BE-F03BAC821358";

static NSString *const MUSE2_TP9_UUID =
    @"273E0003-4C4D-454D-96BE-F03BAC821358";

static NSString *const MUSE2_AF7_UUID =
    @"273E0004-4C4D-454D-96BE-F03BAC821358";

static NSString *const MUSE2_AF8_UUID =
    @"273E0005-4C4D-454D-96BE-F03BAC821358";

static NSString *const MUSE2_TP10_UUID =
    @"273E0006-4C4D-454D-96BE-F03BAC821358";

static NSString *const MUSE2_AUX_UUID =
    @"273E0007-4C4D-454D-96BE-F03BAC821358";


// Set to YES when raw packet logging is needed during debugging.
static const BOOL MUSE2_DEBUG_RAW_PACKETS = NO;


#pragma mark - Weak C callback fallbacks

// The strong definitions in src/muse2_events.c override these fallbacks.
// These keep the Objective-C bridge linkable when built independently.

__attribute__((weak))
void muse2_c_on_connected(const char *device_name) {
    (void)device_name;
}

__attribute__((weak))
void muse2_c_on_service_discovered(const char *uuid) {
    (void)uuid;
}

__attribute__((weak))
void muse2_c_on_characteristic_discovered(
    const char *service_uuid,
    const char *characteristic_uuid
) {
    (void)service_uuid;
    (void)characteristic_uuid;
}

__attribute__((weak))
void muse2_c_on_eeg_packet(
    const char *characteristic_uuid,
    const unsigned char *bytes,
    unsigned long length
) {
    (void)characteristic_uuid;
    (void)bytes;
    (void)length;
}


#pragma mark - Muse scanner interface

@interface MuseScanner : NSObject <
    CBCentralManagerDelegate,
    CBPeripheralDelegate
>

@property (strong, nonatomic) CBCentralManager *centralManager;
@property (strong, nonatomic) CBPeripheral *musePeripheral;

@property (strong, nonatomic) CBCharacteristic *controlCharacteristic;
@property (strong, nonatomic) CBCharacteristic *tp9Characteristic;
@property (strong, nonatomic) CBCharacteristic *af7Characteristic;
@property (strong, nonatomic) CBCharacteristic *af8Characteristic;
@property (strong, nonatomic) CBCharacteristic *tp10Characteristic;
@property (strong, nonatomic) CBCharacteristic *auxCharacteristic;

@property (assign, nonatomic) BOOL ready;
@property (assign, nonatomic) BOOL foundMuse;
@property (assign, nonatomic) BOOL connected;
@property (assign, nonatomic) BOOL discoveryComplete;
@property (assign, nonatomic) BOOL streamingRequested;
@property (assign, nonatomic) NSUInteger eegPacketCount;

@end


#pragma mark - Muse scanner implementation

@implementation MuseScanner


#pragma mark Initialization

- (instancetype)init {
    self = [super init];

    if (self != nil) {
        self.ready = NO;
        self.foundMuse = NO;
        self.connected = NO;
        self.discoveryComplete = NO;
        self.streamingRequested = NO;
        self.eegPacketCount = 0;

        self.centralManager =
            [[CBCentralManager alloc] initWithDelegate:self
                                                 queue:nil];
    }

    return self;
}


#pragma mark Characteristic helpers

- (BOOL)isPrimaryEegCharacteristicUUID:(NSString *)uuid {
    if (uuid == nil) {
        return NO;
    }

    return
        [uuid caseInsensitiveCompare:MUSE2_TP9_UUID] == NSOrderedSame ||
        [uuid caseInsensitiveCompare:MUSE2_AF7_UUID] == NSOrderedSame ||
        [uuid caseInsensitiveCompare:MUSE2_AF8_UUID] == NSOrderedSame ||
        [uuid caseInsensitiveCompare:MUSE2_TP10_UUID] == NSOrderedSame;
}

- (void)storeCharacteristicIfNeeded:
    (CBCharacteristic *)characteristic {

    NSString *uuid = characteristic.UUID.UUIDString;

    if ([uuid caseInsensitiveCompare:MUSE2_CONTROL_UUID] ==
        NSOrderedSame) {

        self.controlCharacteristic = characteristic;

    } else if ([uuid caseInsensitiveCompare:MUSE2_TP9_UUID] ==
               NSOrderedSame) {

        self.tp9Characteristic = characteristic;

    } else if ([uuid caseInsensitiveCompare:MUSE2_AF7_UUID] ==
               NSOrderedSame) {

        self.af7Characteristic = characteristic;

    } else if ([uuid caseInsensitiveCompare:MUSE2_AF8_UUID] ==
               NSOrderedSame) {

        self.af8Characteristic = characteristic;

    } else if ([uuid caseInsensitiveCompare:MUSE2_TP10_UUID] ==
               NSOrderedSame) {

        self.tp10Characteristic = characteristic;

    } else if ([uuid caseInsensitiveCompare:MUSE2_AUX_UUID] ==
               NSOrderedSame) {

        self.auxCharacteristic = characteristic;
    }
}

- (BOOL)hasRequiredCharacteristics {
    return
        self.controlCharacteristic != nil &&
        self.tp9Characteristic != nil &&
        self.af7Characteristic != nil &&
        self.af8Characteristic != nil &&
        self.tp10Characteristic != nil;
}


#pragma mark Muse streaming

- (void)subscribeToEegCharacteristic:
            (CBCharacteristic *)characteristic
                                name:(NSString *)name {

    if (characteristic == nil) {
        NSLog(
            @"Cannot subscribe to %@ because the characteristic is missing.",
            name
        );
        return;
    }

    NSLog(@"Subscribing to %@ EEG notifications...", name);

    [self.musePeripheral setNotifyValue:YES
                      forCharacteristic:characteristic];
}

- (void)subscribeToEegNotifications {
    [self subscribeToEegCharacteristic:self.tp9Characteristic
                                  name:@"TP9"];

    [self subscribeToEegCharacteristic:self.af7Characteristic
                                  name:@"AF7"];

    [self subscribeToEegCharacteristic:self.af8Characteristic
                                  name:@"AF8"];

    [self subscribeToEegCharacteristic:self.tp10Characteristic
                                  name:@"TP10"];
}

- (void)writeMuseCommandString:(NSString *)command {
    if (self.controlCharacteristic == nil) {
        NSLog(
            @"Cannot write Muse command because the control "
             "characteristic is missing."
        );
        return;
    }

    NSData *commandData =
        [command dataUsingEncoding:NSASCIIStringEncoding];

    if (commandData == nil || commandData.length > 253) {
        NSLog(@"Invalid Muse command string.");
        return;
    }

    unsigned char buffer[256];

    buffer[0] = (unsigned char)(commandData.length + 1);

    memcpy(
        buffer + 1,
        commandData.bytes,
        commandData.length
    );

    buffer[commandData.length + 1] = '\n';

    NSData *data = [NSData dataWithBytes:buffer
                                  length:commandData.length + 2];

    NSLog(@"Writing Muse command: %@", command);

    [self.musePeripheral
        writeValue:data
        forCharacteristic:self.controlCharacteristic
        type:CBCharacteristicWriteWithoutResponse];
}

- (void)startMuseStreamingIfReady {
    if (self.streamingRequested) {
        return;
    }

    if (![self hasRequiredCharacteristics]) {
        NSLog(
            @"Cannot start streaming because required "
             "characteristics are missing."
        );
        return;
    }

    [self subscribeToEegNotifications];

    // The Muse command "d" requests legacy EEG streaming.
    // Encoded bytes: 02 64 0A.
    [self writeMuseCommandString:@"d"];

    self.streamingRequested = YES;

    NSLog(@"Muse streaming start requested.");
}


#pragma mark CBCentralManagerDelegate

- (void)centralManagerDidUpdateState:
    (CBCentralManager *)central {

    switch (central.state) {
        case CBManagerStatePoweredOn:
            NSLog(@"Bluetooth is powered on.");

            self.ready = YES;

            NSLog(@"Scanning for BLE devices...");

            [self.centralManager
                scanForPeripheralsWithServices:nil
                options:nil];

            break;

        case CBManagerStatePoweredOff:
            self.ready = NO;
            NSLog(@"Bluetooth is powered off.");
            break;

        case CBManagerStateUnauthorized:
            self.ready = NO;
            NSLog(@"Bluetooth is unauthorized for this app.");
            break;

        case CBManagerStateUnsupported:
            self.ready = NO;
            NSLog(@"Bluetooth is unsupported on this device.");
            break;

        case CBManagerStateResetting:
            self.ready = NO;
            NSLog(@"Bluetooth is resetting.");
            break;

        case CBManagerStateUnknown:
        default:
            self.ready = NO;
            NSLog(@"Bluetooth state is unknown.");
            break;
    }
}

- (void)centralManager:
            (CBCentralManager *)central
     didDiscoverPeripheral:
            (CBPeripheral *)peripheral
     advertisementData:
            (NSDictionary<NSString *, id> *)advertisementData
                  RSSI:
            (NSNumber *)RSSI {

    NSString *name = peripheral.name;

    if (name == nil) {
        name = advertisementData[
            CBAdvertisementDataLocalNameKey
        ];
    }

    if (name == nil) {
        return;
    }

    NSLog(@"Found BLE device: %@ RSSI: %@", name, RSSI);

    if (![name hasPrefix:@"Muse"]) {
        return;
    }

    NSLog(@"Found Muse device: %@", name);

    self.foundMuse = YES;
    self.musePeripheral = peripheral;

    [central stopScan];

    NSLog(@"Connecting to Muse device: %@", name);

    [central connectPeripheral:peripheral
                       options:nil];
}

- (void)centralManager:
            (CBCentralManager *)central
     didConnectPeripheral:
            (CBPeripheral *)peripheral {

    (void)central;

    self.connected = YES;
    self.musePeripheral = peripheral;

    peripheral.delegate = self;

    NSString *name = peripheral.name;

    if (name == nil) {
        name = @"UNKNOWN";
    }

    NSLog(@"Connected to Muse device: %@", name);

    muse2_c_on_connected([name UTF8String]);

    NSLog(@"Discovering services...");

    [peripheral discoverServices:nil];
}

- (void)centralManager:
            (CBCentralManager *)central
     didFailToConnectPeripheral:
            (CBPeripheral *)peripheral
                         error:
            (NSError *)error {

    (void)central;

    self.connected = NO;
    self.streamingRequested = NO;

    NSLog(
        @"Failed to connect to Muse device: %@ error: %@",
        peripheral.name,
        error
    );
}

- (void)centralManager:
            (CBCentralManager *)central
     didDisconnectPeripheral:
            (CBPeripheral *)peripheral
                       error:
            (NSError *)error {

    self.connected = NO;
    self.discoveryComplete = NO;
    self.streamingRequested = NO;

    self.controlCharacteristic = nil;
    self.tp9Characteristic = nil;
    self.af7Characteristic = nil;
    self.af8Characteristic = nil;
    self.tp10Characteristic = nil;
    self.auxCharacteristic = nil;

    NSLog(
        @"Disconnected from Muse device: %@ error: %@",
        peripheral.name,
        error
    );

    // Resume scanning so the application can reconnect if the Muse
    // becomes available again.
    if (central.state == CBManagerStatePoweredOn) {
        self.foundMuse = NO;

        NSLog(@"Scanning for Muse device again...");

        [central scanForPeripheralsWithServices:nil
                                       options:nil];
    }
}


#pragma mark CBPeripheralDelegate

- (void)peripheral:
            (CBPeripheral *)peripheral
     didDiscoverServices:
            (NSError *)error {

    if (error != nil) {
        NSLog(@"Failed to discover services: %@", error);
        return;
    }

    if (peripheral.services.count == 0) {
        NSLog(@"No services discovered.");
        return;
    }

    for (CBService *service in peripheral.services) {
        NSString *serviceUUID =
            service.UUID.UUIDString;

        NSLog(@"Service: %@", serviceUUID);

        muse2_c_on_service_discovered(
            [serviceUUID UTF8String]
        );

        [peripheral discoverCharacteristics:nil
                                 forService:service];
    }
}

- (void)peripheral:
            (CBPeripheral *)peripheral
     didDiscoverCharacteristicsForService:
            (CBService *)service
             error:
            (NSError *)error {

    (void)peripheral;

    if (error != nil) {
        NSLog(
            @"Failed to discover characteristics for service %@: %@",
            service.UUID.UUIDString,
            error
        );
        return;
    }

    NSString *serviceUUID =
        service.UUID.UUIDString;

    for (CBCharacteristic *characteristic
         in service.characteristics) {

        NSString *characteristicUUID =
            characteristic.UUID.UUIDString;

        NSLog(
            @"Characteristic for service %@: %@",
            serviceUUID,
            characteristicUUID
        );

        [self storeCharacteristicIfNeeded:characteristic];

        muse2_c_on_characteristic_discovered(
            [serviceUUID UTF8String],
            [characteristicUUID UTF8String]
        );
    }

    BOOL allServicesHaveCharacteristics = YES;

    for (CBService *knownService
         in self.musePeripheral.services) {

        if (knownService.characteristics == nil) {
            allServicesHaveCharacteristics = NO;
            break;
        }
    }

    if (!allServicesHaveCharacteristics) {
        return;
    }

    self.discoveryComplete = YES;

    NSLog(@"GATT discovery complete.");

    if (![self hasRequiredCharacteristics]) {
        NSLog(
            @"GATT discovery completed, but required Muse "
             "characteristics are missing."
        );
        return;
    }

    NSLog(@"Required Muse EEG/control characteristics found.");

    [self startMuseStreamingIfReady];
}

- (void)peripheral:
            (CBPeripheral *)peripheral
     didUpdateNotificationStateForCharacteristic:
            (CBCharacteristic *)characteristic
             error:
            (NSError *)error {

    (void)peripheral;

    NSString *uuid =
        characteristic.UUID.UUIDString;

    if (error != nil) {
        NSLog(
            @"Failed to update notification state for %@: %@",
            uuid,
            error
        );
        return;
    }

    NSLog(
        @"Notification state for %@ is %@",
        uuid,
        characteristic.isNotifying ? @"ON" : @"OFF"
    );
}

- (void)peripheral:
            (CBPeripheral *)peripheral
     didUpdateValueForCharacteristic:
            (CBCharacteristic *)characteristic
             error:
            (NSError *)error {

    (void)peripheral;

    NSString *uuid =
        characteristic.UUID.UUIDString;

    if (error != nil) {
        NSLog(
            @"Failed to read/update value for %@: %@",
            uuid,
            error
        );
        return;
    }

    NSData *value = characteristic.value;

    if (value == nil || value.length == 0) {
        return;
    }

    if (![self isPrimaryEegCharacteristicUUID:uuid]) {
        return;
    }

    self.eegPacketCount += 1;

    const unsigned char *bytes =
        (const unsigned char *)value.bytes;

    unsigned long length =
        (unsigned long)value.length;

    muse2_c_on_eeg_packet(
        [uuid UTF8String],
        bytes,
        length
    );

    if (MUSE2_DEBUG_RAW_PACKETS &&
        self.eegPacketCount <= 10) {

        NSMutableString *hex =
            [NSMutableString
                stringWithCapacity:value.length * 3];

        for (NSUInteger i = 0;
             i < value.length;
             i++) {

            [hex appendFormat:@"%02X", bytes[i]];

            if (i + 1 < value.length) {
                [hex appendString:@" "];
            }
        }

        NSLog(
            @"EEG packet %@ length=%lu bytes=%@",
            uuid,
            length,
            hex
        );
    }
}

@end


#pragma mark - Program entry point

int main(void) {
    @autoreleasepool {
        NSLog(@"Muse 2 BLE scanner starting...");
        NSLog(@"Streaming continuously. Press Ctrl+C to stop.");

        MuseScanner *scanner =
            [[MuseScanner alloc] init];

        // Keep the scanner alive while CoreBluetooth uses the current
        // thread's run loop for asynchronous delegate callbacks.
        (void)scanner;

        [[NSRunLoop currentRunLoop] run];
    }

    return 0;
}