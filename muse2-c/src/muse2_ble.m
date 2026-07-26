// Thin Objective-C/CoreBluetooth adapter for Muse 2 BLE access.
// Keep this file focused on macOS Bluetooth mechanics only.
// Put packet decoding, validation, buffering, and project logic in C files.

#import <Foundation/Foundation.h>
#import <CoreBluetooth/CoreBluetooth.h>
#import "muse2_ble.h"

// Muse 2 characteristic UUIDs used by the Objective-C BLE adapter.
// These are kept here only because CoreBluetooth must store CBCharacteristic objects.
static NSString * const MUSE2_CONTROL_UUID = @"273E0001-4C4D-454D-96BE-F03BAC821358";
static NSString * const MUSE2_TP9_UUID     = @"273E0003-4C4D-454D-96BE-F03BAC821358";
static NSString * const MUSE2_AF7_UUID     = @"273E0004-4C4D-454D-96BE-F03BAC821358";
static NSString * const MUSE2_AF8_UUID     = @"273E0005-4C4D-454D-96BE-F03BAC821358";
static NSString * const MUSE2_TP10_UUID    = @"273E0006-4C4D-454D-96BE-F03BAC821358";
static NSString * const MUSE2_AUX_UUID     = @"273E0007-4C4D-454D-96BE-F03BAC821358";

// Weak fallback implementations for the C hooks declared in muse2_ble.h.
// When src/muse2_events.c defines these same functions, the C definitions win.
// This keeps the Objective-C bridge buildable during early bring-up.
__attribute__((weak)) void muse2_c_on_connected(const char *device_name) {
    (void)device_name;
}

__attribute__((weak)) void muse2_c_on_service_discovered(const char *uuid) {
    (void)uuid;
}

__attribute__((weak)) void muse2_c_on_characteristic_discovered(const char *service_uuid,
                                                               const char *characteristic_uuid) {
    (void)service_uuid;
    (void)characteristic_uuid;
}

__attribute__((weak)) void muse2_c_on_eeg_packet(const char *characteristic_uuid,
                                                const unsigned char *bytes,
                                                unsigned long length) {
    (void)characteristic_uuid;
    (void)bytes;
    (void)length;
}

@interface MuseScanner : NSObject <CBCentralManagerDelegate, CBPeripheralDelegate>

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
@property (assign, nonatomic) BOOL streamingStarted;
@property (assign, nonatomic) NSUInteger eegPacketCount;

@end

@implementation MuseScanner

- (instancetype)init {
    self = [super init];

    if (self) {
        self.ready = NO;
        self.foundMuse = NO;
        self.connected = NO;
        self.discoveryComplete = NO;
        self.streamingStarted = NO;
        self.eegPacketCount = 0;
        self.centralManager = [[CBCentralManager alloc] initWithDelegate:self queue:nil];
    }

    return self;
}

- (BOOL)isEegCharacteristicUUID:(NSString *)uuid {
    return [uuid caseInsensitiveCompare:MUSE2_TP9_UUID] == NSOrderedSame ||
           [uuid caseInsensitiveCompare:MUSE2_AF7_UUID] == NSOrderedSame ||
           [uuid caseInsensitiveCompare:MUSE2_AF8_UUID] == NSOrderedSame ||
           [uuid caseInsensitiveCompare:MUSE2_TP10_UUID] == NSOrderedSame ||
           [uuid caseInsensitiveCompare:MUSE2_AUX_UUID] == NSOrderedSame;
}

- (void)storeCharacteristicIfNeeded:(CBCharacteristic *)characteristic {
    NSString *uuid = characteristic.UUID.UUIDString;

    if ([uuid caseInsensitiveCompare:MUSE2_CONTROL_UUID] == NSOrderedSame) {
        self.controlCharacteristic = characteristic;
    } else if ([uuid caseInsensitiveCompare:MUSE2_TP9_UUID] == NSOrderedSame) {
        self.tp9Characteristic = characteristic;
    } else if ([uuid caseInsensitiveCompare:MUSE2_AF7_UUID] == NSOrderedSame) {
        self.af7Characteristic = characteristic;
    } else if ([uuid caseInsensitiveCompare:MUSE2_AF8_UUID] == NSOrderedSame) {
        self.af8Characteristic = characteristic;
    } else if ([uuid caseInsensitiveCompare:MUSE2_TP10_UUID] == NSOrderedSame) {
        self.tp10Characteristic = characteristic;
    } else if ([uuid caseInsensitiveCompare:MUSE2_AUX_UUID] == NSOrderedSame) {
        self.auxCharacteristic = characteristic;
    }
}

- (BOOL)hasRequiredCharacteristics {
    return self.controlCharacteristic != nil &&
           self.tp9Characteristic != nil &&
           self.af7Characteristic != nil &&
           self.af8Characteristic != nil &&
           self.tp10Characteristic != nil;
}

- (void)subscribeToEegCharacteristic:(CBCharacteristic *)characteristic
                                name:(NSString *)name {
    if (characteristic == nil) {
        NSLog(@"Cannot subscribe to %@ because characteristic is missing.", name);
        return;
    }

    NSLog(@"Subscribing to %@ EEG notifications...", name);
    [self.musePeripheral setNotifyValue:YES forCharacteristic:characteristic];
}

- (void)subscribeToEegNotifications {
    [self subscribeToEegCharacteristic:self.tp9Characteristic name:@"TP9"];
    [self subscribeToEegCharacteristic:self.af7Characteristic name:@"AF7"];
    [self subscribeToEegCharacteristic:self.af8Characteristic name:@"AF8"];
    [self subscribeToEegCharacteristic:self.tp10Characteristic name:@"TP10"];

    // AUX is optional for the current C workflow. Subscribe if it exists.
    if (self.auxCharacteristic != nil) {
        [self subscribeToEegCharacteristic:self.auxCharacteristic name:@"AUX"];
    }
}

- (void)writeMuseCommandString:(NSString *)command {
    if (self.controlCharacteristic == nil) {
        NSLog(@"Cannot write Muse command because control characteristic is missing.");
        return;
    }

    NSData *commandData = [command dataUsingEncoding:NSASCIIStringEncoding];
    if (commandData == nil || commandData.length > 253) {
        NSLog(@"Invalid Muse command string.");
        return;
    }

    unsigned char buffer[256];
    buffer[0] = (unsigned char)(commandData.length + 1);
    memcpy(buffer + 1, commandData.bytes, commandData.length);
    buffer[commandData.length + 1] = '\n';

    NSData *data = [NSData dataWithBytes:buffer length:commandData.length + 2];

    NSLog(@"Writing Muse command: %@", command);
    [self.musePeripheral writeValue:data
                  forCharacteristic:self.controlCharacteristic
                               type:CBCharacteristicWriteWithoutResponse];
}

- (void)startMuseStreamingIfReady {
    if (self.streamingStarted) {
        return;
    }

    if (![self hasRequiredCharacteristics]) {
        NSLog(@"Cannot start streaming because required characteristics are missing.");
        return;
    }

    [self subscribeToEegNotifications];

    // muselsl uses command string "d" to resume/start legacy Muse EEG streaming.
    // Encoding is: length byte, ASCII command bytes, newline.
    // For "d", bytes are: 02 64 0A.
    [self writeMuseCommandString:@"d"];

    self.streamingStarted = YES;
    NSLog(@"Muse streaming start requested.");
}

- (void)centralManagerDidUpdateState:(CBCentralManager *)central {
    switch (central.state) {
        case CBManagerStatePoweredOn:
            NSLog(@"Bluetooth is powered on.");
            self.ready = YES;
            NSLog(@"Scanning for BLE devices...");
            [self.centralManager scanForPeripheralsWithServices:nil options:nil];
            break;

        case CBManagerStatePoweredOff:
            NSLog(@"Bluetooth is powered off.");
            break;

        case CBManagerStateUnauthorized:
            NSLog(@"Bluetooth is unauthorized for this app.");
            break;

        case CBManagerStateUnsupported:
            NSLog(@"Bluetooth is unsupported on this device.");
            break;

        case CBManagerStateResetting:
            NSLog(@"Bluetooth is resetting.");
            break;

        case CBManagerStateUnknown:
        default:
            NSLog(@"Bluetooth state is unknown.");
            break;
    }
}

- (void)centralManager:(CBCentralManager *)central
 didDiscoverPeripheral:(CBPeripheral *)peripheral
     advertisementData:(NSDictionary<NSString *, id> *)advertisementData
                  RSSI:(NSNumber *)RSSI {

    NSString *name = peripheral.name;

    if (name == nil) {
        name = advertisementData[CBAdvertisementDataLocalNameKey];
    }

    if (name == nil) {
        return;
    }

    NSLog(@"Found BLE device: %@ RSSI: %@", name, RSSI);

    if ([name hasPrefix:@"Muse"]) {
        NSLog(@"Found Muse device: %@", name);
        self.foundMuse = YES;
        self.musePeripheral = peripheral;
        [central stopScan];

        NSLog(@"Connecting to Muse device: %@", name);
        [central connectPeripheral:peripheral options:nil];
    }
}

- (void)centralManager:(CBCentralManager *)central
  didConnectPeripheral:(CBPeripheral *)peripheral {
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

- (void)centralManager:(CBCentralManager *)central
    didFailToConnectPeripheral:(CBPeripheral *)peripheral
                         error:(NSError *)error {
    (void)central;
    NSLog(@"Failed to connect to Muse device: %@ error: %@", peripheral.name, error);
}

- (void)centralManager:(CBCentralManager *)central
 didDisconnectPeripheral:(CBPeripheral *)peripheral
                 error:(NSError *)error {
    (void)central;
    self.connected = NO;
    self.discoveryComplete = NO;
    self.streamingStarted = NO;
    NSLog(@"Disconnected from Muse device: %@ error: %@", peripheral.name, error);
}

- (void)peripheral:(CBPeripheral *)peripheral
 didDiscoverServices:(NSError *)error {
    if (error != nil) {
        NSLog(@"Failed to discover services: %@", error);
        return;
    }

    if (peripheral.services.count == 0) {
        NSLog(@"No services discovered.");
        self.discoveryComplete = YES;
        return;
    }

    for (CBService *service in peripheral.services) {
        NSString *serviceUUID = service.UUID.UUIDString;
        NSLog(@"Service: %@", serviceUUID);
        muse2_c_on_service_discovered([serviceUUID UTF8String]);
        [peripheral discoverCharacteristics:nil forService:service];
    }
}

- (void)peripheral:(CBPeripheral *)peripheral
 didDiscoverCharacteristicsForService:(CBService *)service
             error:(NSError *)error {
    (void)peripheral;

    if (error != nil) {
        NSLog(@"Failed to discover characteristics for service %@: %@", service.UUID.UUIDString, error);
        return;
    }

    NSString *serviceUUID = service.UUID.UUIDString;

    for (CBCharacteristic *characteristic in service.characteristics) {
        NSString *characteristicUUID = characteristic.UUID.UUIDString;
        NSLog(@"Characteristic for service %@: %@", serviceUUID, characteristicUUID);

        [self storeCharacteristicIfNeeded:characteristic];

        muse2_c_on_characteristic_discovered([serviceUUID UTF8String],
                                             [characteristicUUID UTF8String]);
    }

    BOOL allServicesHaveCharacteristics = YES;

    for (CBService *knownService in self.musePeripheral.services) {
        if (knownService.characteristics == nil) {
            allServicesHaveCharacteristics = NO;
            break;
        }
    }

    if (allServicesHaveCharacteristics) {
        self.discoveryComplete = YES;
        NSLog(@"GATT discovery complete.");

        if ([self hasRequiredCharacteristics]) {
            NSLog(@"Required Muse EEG/control characteristics found.");
            [self startMuseStreamingIfReady];
        } else {
            NSLog(@"GATT discovery complete, but required Muse characteristics are missing.");
        }
    }
}

- (void)peripheral:(CBPeripheral *)peripheral
 didUpdateNotificationStateForCharacteristic:(CBCharacteristic *)characteristic
             error:(NSError *)error {
    (void)peripheral;

    NSString *uuid = characteristic.UUID.UUIDString;

    if (error != nil) {
        NSLog(@"Failed to update notification state for %@: %@", uuid, error);
        return;
    }

    NSLog(@"Notification state for %@ is %@", uuid, characteristic.isNotifying ? @"ON" : @"OFF");
}

- (void)peripheral:(CBPeripheral *)peripheral
 didUpdateValueForCharacteristic:(CBCharacteristic *)characteristic
             error:(NSError *)error {
    (void)peripheral;

    NSString *uuid = characteristic.UUID.UUIDString;

    if (error != nil) {
        NSLog(@"Failed to read/update value for %@: %@", uuid, error);
        return;
    }

    NSData *value = characteristic.value;
    if (value == nil || value.length == 0) {
        return;
    }

    if (![self isEegCharacteristicUUID:uuid]) {
        return;
    }

    self.eegPacketCount += 1;

    const unsigned char *bytes = (const unsigned char *)value.bytes;
    unsigned long length = (unsigned long)value.length;

    muse2_c_on_eeg_packet([uuid UTF8String], bytes, length);

    if (self.eegPacketCount <= 10) {
        NSMutableString *hex = [NSMutableString stringWithCapacity:value.length * 3];
        for (NSUInteger i = 0; i < value.length; i++) {
            [hex appendFormat:@"%02X", bytes[i]];
            if (i + 1 < value.length) {
                [hex appendString:@" "];
            }
        }

        NSLog(@"EEG packet %@ length=%lu bytes=%@", uuid, length, hex);
    }
}

@end

int main(void) {
    @autoreleasepool {
        NSLog(@"Muse 2 BLE scanner starting...");

        MuseScanner *scanner = [[MuseScanner alloc] init];

        while (YES) {
            [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode
                                     beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.1]];

            if (!scanner.ready) {
                continue;
            }

            if (scanner.connected && scanner.streamingStarted) {
                continue;
            }

            if (!scanner.foundMuse && scanner.ready) {
                continue;
            }
        }

        if (!scanner.ready) {
            NSLog(@"Bluetooth did not become ready within timeout.");
            return 1;
        }

        if (!scanner.foundMuse) {
            NSLog(@"No Muse device found within timeout.");
            return 1;
        }

        if (!scanner.connected) {
            NSLog(@"Muse device found but connection did not complete within timeout.");
            return 1;
        }

        if (!scanner.discoveryComplete) {
            NSLog(@"Muse connected but GATT discovery did not complete within timeout.");
            return 1;
        }

        if (!scanner.streamingStarted) {
            NSLog(@"Muse GATT discovery completed but streaming was not started.");
            return 1;
        }

        if (scanner.eegPacketCount == 0) {
            NSLog(@"Streaming was requested, but no EEG packets were received within timeout.");
            return 1;
        }

    }

    return 0;
}
