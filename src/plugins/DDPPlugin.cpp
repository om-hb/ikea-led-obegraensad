#include "plugins/DDPPlugin.h"

// Static pointer for callback access
static DDPPlugin *instance = nullptr;

// Frame buffer in DRAM for faster ISR access on ESP32
#ifdef ESP32
static DRAM_ATTR uint8_t ddpFrameBuffer[ROWS * COLS];
#else
static uint8_t ddpFrameBuffer[ROWS * COLS];
#endif

void DDPPlugin::applyBufferToScreen()
{
  for (int i = 0; i < ROWS * COLS; i++)
  {
    // Quantize 0-255 to 0-15 for 4-bit display
    uint8_t brightness = ddpFrameBuffer[i] >> 4;
    Screen.setPixelAtIndex(i, brightness > 0, brightness);
  }
  bufferDirty = false;
}

void DDPPlugin::setup()
{
  instance = this;
  memset(ddpFrameBuffer, 0, ROWS * COLS);

#ifdef ASYNC_UDP_ENABLED
  udp = new AsyncUDP();
  if (!udp->listen(4048))
  {
    Serial.println("DDP: Failed to listen on port 4048");
    delete udp;
    udp = nullptr;
    return;
  }

  Serial.println("DDP server listening at port: 4048");

  udp->onPacket([](AsyncUDPPacket packet) {
      if (packet.length() < 10 || instance == nullptr)
        return;

      const uint8_t flags = packet.data()[0];
      const bool push = (flags & DDP_FLAG_PUSH) != 0;
      const uint8_t dataType = packet.data()[3];
      const uint8_t *data = packet.data() + 10; // Skip header
      const size_t dataLength = packet.length() - 10;

      // If packet has pixel data, write to buffer
      if (dataLength > 0)
      {
        if (dataType == DDP_TYPE_GRAYSCALE)
        {
          // 1 byte per pixel (0-255), direct copy
          int count = std::min((int)dataLength, ROWS * COLS);
          memcpy(ddpFrameBuffer, data, count);
        }
        else
        {
          // Legacy RGB mode: 3 bytes per pixel
          int count = std::min((int)(dataLength / 3), ROWS * COLS);
          if (count == 1)
          {
            // Single pixel mode - fill entire buffer
            uint16_t sum = data[0] + data[1] + data[2];
            uint8_t brightness = (sum * 85) >> 8;
            memset(ddpFrameBuffer, brightness, ROWS * COLS);
          }
          else
          {
            for (int i = 0; i < count; i++)
            {
              // Average RGB to grayscale using multiply-shift (faster than division)
              // (sum * 85) >> 8 ≈ sum / 3
              uint16_t sum = data[i * 3] + data[i * 3 + 1] + data[i * 3 + 2];
              ddpFrameBuffer[i] = (sum * 85) >> 8;
            }
          }
        }
        instance->bufferDirty = true;
      }

      // Push flag: always apply buffer to screen
      // (even if not dirty, to handle packet loss gracefully)
      if (push)
      {
        instance->applyBufferToScreen();
      }
    });
#endif
}

void DDPPlugin::teardown()
{
  instance = nullptr;
#ifdef ASYNC_UDP_ENABLED
  if (udp)
  {
    delete udp;
    udp = nullptr;
  }
#endif
}

void DDPPlugin::loop()
{
  // Apply buffer if dirty (for senders that don't use push flag)
  if (bufferDirty)
  {
    applyBufferToScreen();
  }

#ifdef ESP32
  vTaskDelay(10);
#else
  delay(10);
#endif
}

const char *DDPPlugin::getName() const
{
  return "DDP";
}