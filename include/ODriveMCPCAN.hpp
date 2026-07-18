// Glue layer for MCP2515-based CAN interfaces.
// See ODriveHardwareCAN.hpp for documentation.

#pragma once

#include "MCP2515.h"
#include "ODriveCAN.h"

// This is a convenience struct because the MCP2515 library doesn't have a
// native message type.
struct CanMsg {
    uint32_t id;
    uint8_t len;
    uint8_t buffer[8];
};

// Must be defined by the application if you want to use defaultCanReceiveCallback().
void onCanMessage(const CanMsg& msg);

// MSB of id means "extended"
// if data is null, it's a remote request frame
static bool sendMsg(MCP2515Class& can_intf, uint32_t id, uint8_t length, const uint8_t* data) {
    if (id & 0x80000000) {
        can_intf.beginExtendedPacket(id & 0x1fffffff, length, !data);
    } else {
        can_intf.beginPacket(id, length, !data);
    }
    if (data) {
        for (int i = 0; i < length; ++i) {
            can_intf.write(data[i]);
        }
    }
    return can_intf.endPacket();
}

static void pumpEvents(MCP2515Class& intf) {
    // Poll the MCP2515 directly. This makes ODrive reception independent of
    // the controller's INT pin and also services replies while request() is
    // waiting for them.
    while (true) {
        int packet_size = intf.parsePacket();
        if (packet_size <= 0) {
            return;
        }
        if (packet_size > 8) {
            while (intf.available()) intf.read();
            continue;
        }

        CanMsg msg = {
            .id = static_cast<uint32_t>(intf.packetId()),
            .len = static_cast<uint8_t>(packet_size),
        };
        intf.readBytes(msg.buffer, msg.len);
        onCanMessage(msg);
    }
}

CREATE_CAN_INTF_WRAPPER(MCP2515Class)
