#pragma once

#include "PluginManager.h"
#include "Screen.h"
#if __has_include("AsyncUDP.h")
#include "AsyncUDP.h"
#define ASYNC_UDP_ENABLED
#endif

// DDP Protocol flags
#define DDP_FLAG_PUSH 0x01    // Bit 0: Push - render frame now
#define DDP_FLAG_QUERY 0x02   // Bit 1: Query
#define DDP_FLAG_REPLY 0x04   // Bit 2: Reply
#define DDP_FLAG_STORAGE 0x08 // Bit 3: Storage
#define DDP_FLAG_TIME 0x10    // Bit 4: Timecode present

// DDP Data types (byte 3 in header)
#define DDP_TYPE_RGB 0x01       // 3 bytes per pixel (R, G, B)
#define DDP_TYPE_GRAYSCALE 0x02 // 1 byte per pixel (brightness 0-15)

class DDPPlugin : public Plugin
{
private:
#ifdef ASYNC_UDP_ENABLED
  AsyncUDP *udp = nullptr;
#endif
  volatile bool bufferDirty = false;

  void applyBufferToScreen();

public:
  void setup() override;
  void teardown() override;
  void loop() override;
  const char *getName() const override;
};
