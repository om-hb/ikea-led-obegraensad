#include "plugins/ArtNet.h"

void ArtNetPlugin::setup()
{
  artnet.begin();
  artnet.setArtDmxCallback(onDmxFrame);
  Serial.print("ArtNet server listening at IP: ");
  Serial.print(WiFi.localIP());
  Serial.print(" port: ");
  Serial.println(ART_NET_PORT);
  artnet.setUniverse(1);
  Serial.print("Universe: ");
  Serial.println(artnet.getOutgoing());
}

void ArtNetPlugin::teardown()
{
  artnet.stop();
}

void ArtNetPlugin::loop()
{
  artnet.read();

#ifdef ESP32
  vTaskDelay(1);  // Feed watchdog, allow other tasks to run
#else
  delay(1);
#endif
}

const char *ArtNetPlugin::getName() const
{
  return "ArtNet";
}

void ArtNetPlugin::onDmxFrame(uint16_t universe, uint16_t length, uint16_t outgoing, uint8_t *data)
{
  if (universe == 0 || universe == outgoing)
  {
    for (int i = 0; i < ROWS * COLS; i++)
    {
      Screen.setPixelAtIndex(i, data[i] > 4, data[i]);
    }
  }
}

void ArtNetPlugin::websocketHook(JsonDocument &request)
{
  const char *event = request["event"];

  if (event == nullptr || currentStatus != NONE)
  {
    return;
  }

  if (!strcmp(event, "artnet"))
  {
    uint16_t universe = request["universe"].as<uint16_t>();
    Serial.printf("[ArtNet] Changing universe to %d\n", universe);
    artnet.setUniverse(universe);
  }
}
