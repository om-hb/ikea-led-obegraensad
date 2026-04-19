#include "PluginManager.h"
#include "scheduler.h"

#ifdef ENABLE_SERVER

AsyncWebSocket ws("/ws");

// Rate limiting for WebSocket messages
static unsigned long lastWsMessage = 0;
static const unsigned long WS_MIN_INTERVAL_MS = 50;  // Max 20 messages/second

// Rate limiting for sendInfo broadcasts
static unsigned long lastSendInfo = 0;
static const unsigned long SEND_INFO_MIN_INTERVAL_MS = 100;  // Max 10 broadcasts/second

void sendInfo()
{
  // Don't send if no clients connected
  if (ws.count() == 0)
  {
    return;
  }

  // Rate limit broadcasts to prevent overwhelming the WebSocket system
  unsigned long now = millis();
  if (now - lastSendInfo < SEND_INFO_MIN_INTERVAL_MS)
  {
    return;
  }
  lastSendInfo = now;

  // Clean up disconnected clients first to prevent queue buildup
  ws.cleanupClients();

  JsonDocument jsonDocument;
  if (currentStatus == NONE)
  {
    for (int j = 0; j < ROWS * COLS; j++)
    {
      jsonDocument["data"][j] = Screen.getRenderBuffer()[j];
    }
  }

  jsonDocument["status"] = currentStatus;
  Plugin *activePlugin = pluginManager.getActivePlugin();
  jsonDocument["plugin"] = activePlugin ? activePlugin->getId() : -1;
  jsonDocument["persist-plugin"] = pluginManager.getPersistedPluginId();
  jsonDocument["event"] = "info";
  jsonDocument["rotation"] = Screen.currentRotation;
  jsonDocument["brightness"] = Screen.getCurrentBrightness();
  jsonDocument["scheduleActive"] = Scheduler.isActive;

  JsonArray scheduleArray = jsonDocument["schedule"].to<JsonArray>();
  for (const auto &item : Scheduler.schedule)
  {
    JsonObject scheduleItem = scheduleArray.add<JsonObject>();
    scheduleItem["pluginId"] = item.pluginId;
    scheduleItem["duration"] = item.duration / 1000; // Convert milliseconds to seconds
  }

  JsonArray plugins = jsonDocument["plugins"].to<JsonArray>();

  std::vector<Plugin *> &allPlugins = pluginManager.getAllPlugins();
  for (Plugin *plugin : allPlugins)
  {
    JsonObject object = plugins.add<JsonObject>();

    object["id"] = plugin->getId();
    object["name"] = plugin->getName();
  }
  String output;
  serializeJson(jsonDocument, output);
  ws.textAll(output);
  jsonDocument.clear();
}

void sendWSMessage(String &message) {
  ws.textAll(message);
}

void onWsEvent(AsyncWebSocket *server,
               AsyncWebSocketClient *client,
               AwsEventType type,
               void *arg,
               uint8_t *data,
               size_t len)
{
  if (type == WS_EVT_CONNECT)
  {
    sendInfo();
  }

  if (type == WS_EVT_DATA)
  {
    AwsFrameInfo *info = (AwsFrameInfo *)arg;
    if (info->final && info->index == 0 && info->len == len)
    {
      if (info->opcode == WS_BINARY && currentStatus == WSBINARY && info->len == 256)
      {
        Screen.setRenderBuffer(data, true);
      }
      else if (info->opcode == WS_TEXT)
      {
        // Rate limiting: ignore messages that come too fast
        unsigned long now = millis();
        if (now - lastWsMessage < WS_MIN_INTERVAL_MS)
        {
          return;  // Drop message if too fast
        }
        lastWsMessage = now;

        data[len] = 0;

        JsonDocument wsRequest;
        DeserializationError error = deserializeJson(wsRequest, data);

        if (error)
        {
          Serial.print(F("deserializeJson() failed: "));
          Serial.println(error.f_str());
          return;
        }
        else
        {
          Plugin *activePlugin = pluginManager.getActivePlugin();
          if (activePlugin)
          {
            activePlugin->websocketHook(wsRequest);
          }

          const char *event = wsRequest["event"];

          // Guard against null event (malformed JSON or missing field)
          if (event == nullptr)
          {
            return;
          }

          if (!strcmp(event, "plugin"))
          {
            int pluginId = wsRequest["plugin"];

            Scheduler.clearSchedule();
            // Use non-blocking request to avoid blocking async_tcp task
            pluginManager.requestPluginById(pluginId);
            // sendInfo() will be called by processPendingPluginChange()
          }
          else if (!strcmp(event, "persist-plugin"))
          {
            pluginManager.persistActivePlugin();
            sendInfo();
          }
          else if (!strcmp(event, "rotate"))
          {
            bool isRight = (bool)!strcmp(wsRequest["direction"], "right");
            Screen.setCurrentRotation((Screen.currentRotation + (isRight ? 1 : 3)) % 4, true);
            sendInfo();
          }
          else if (!strcmp(event, "info"))
          {
            sendInfo();
          }
          else if (!strcmp(event, "brightness"))
          {
            uint8_t brightness = wsRequest["brightness"].as<uint8_t>();
            Screen.setBrightness(brightness, true);
            sendInfo();
          }
        }
      }
    }
  }
}

void initWebsocketServer(AsyncWebServer &server)
{
  server.addHandler(&ws);
  ws.onEvent(onWsEvent);
}

void cleanUpClients()
{
  ws.cleanupClients();
}

#endif
