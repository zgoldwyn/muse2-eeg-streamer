CC = clang
CFLAGS = -Wall -Wextra -std=c11 -Iinclude
BUILD_DIR = build

.PHONY: all test clean

all: test_decode

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

test_decode: $(BUILD_DIR) src/muse2_decode.c tests/test_decode.c include/muse2_decode.h include/muse2_constants.h
	$(CC) $(CFLAGS) src/muse2_decode.c tests/test_decode.c -o $(BUILD_DIR)/test_decode

test: test_decode
	./$(BUILD_DIR)/test_decode

scan:
	clang -Wall -Wextra -Iinclude src/muse2_ble.m src/muse2_events.c src/muse2_decode.c \
		-framework Foundation \
		-framework CoreBluetooth \
		-o build/muse2_scan



clean:
	rm -rf $(BUILD_DIR)