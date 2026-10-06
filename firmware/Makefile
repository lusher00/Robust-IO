# Robust IO firmware - ATmega1284P, 12 MHz, avr-gcc
# Targets: all, size, flash, fuses, clean
# Programmer defaults are for a Raspberry Pi wired to J1 (see DESIGN.md section 4).

MCU        = atmega1284p
AVRDUDE_MCU= m1284p
TARGET     = robust-io
BUILD      = build

PROGRAMMER ?= linuxspi
PORT       ?= /dev/spidev0.0:/dev/gpiochip0:25
SPI_HZ     ?= 1000000
SPI_HZ_SLOW = 100000

LFUSE = 0xFF   # external crystal 8-16 MHz
HFUSE = 0xD1   # JTAG off, SPI programming on, EEPROM kept through chip erase
EFUSE = 0xFD   # brown-out 2.7 V

VERSION := $(shell git describe --always --dirty 2>/dev/null || echo unknown)

CC      = avr-gcc
OBJCOPY = avr-objcopy
SIZE    = avr-size
AVRDUDE = avrdude

SRCS := $(wildcard src/*.c src/hal/*.c src/drivers/*.c src/app/*.c)
OBJS := $(patsubst src/%.c,$(BUILD)/%.o,$(SRCS))
DEPS := $(OBJS:.o=.d)

CFLAGS  = -mmcu=$(MCU) -std=gnu11 -Os -g -Isrc \
          -Wall -Wextra -Wshadow -Wstrict-prototypes -Wundef \
          -ffunction-sections -fdata-sections -fshort-enums \
          -MMD -MP -DFW_VERSION=\"$(VERSION)\"
LDFLAGS = -mmcu=$(MCU) -Wl,--gc-sections -Wl,-Map,$(BUILD)/$(TARGET).map

.PHONY: all size flash fuses clean

all: $(BUILD)/$(TARGET).hex size

$(BUILD)/%.o: src/%.c
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD)/$(TARGET).elf: $(OBJS)
	$(CC) $(LDFLAGS) $^ -o $@

$(BUILD)/$(TARGET).hex: $(BUILD)/$(TARGET).elf
	$(OBJCOPY) -O ihex -R .eeprom $< $@

size: $(BUILD)/$(TARGET).elf
	$(SIZE) $<

# A new chip runs from its 1 MHz internal clock, so fuses are written slowly.
fuses:
	$(AVRDUDE) -c $(PROGRAMMER) -P $(PORT) -p $(AVRDUDE_MCU) -b $(SPI_HZ_SLOW) \
	  -U lfuse:w:$(LFUSE):m -U hfuse:w:$(HFUSE):m -U efuse:w:$(EFUSE):m

flash: $(BUILD)/$(TARGET).hex
	$(AVRDUDE) -c $(PROGRAMMER) -P $(PORT) -p $(AVRDUDE_MCU) -b $(SPI_HZ) \
	  -U flash:w:$<:i

clean:
	rm -rf $(BUILD)

-include $(DEPS)
