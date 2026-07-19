#pragma once

#ifdef ESP32
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <atomic>
#endif
#ifdef ESP8266
#include <ESP8266HTTPClient.h>
#include <ESP8266WiFi.h>
#include <WiFiClient.h>
#endif
#include "PluginManager.h"
#include <ArduinoJson.h>
class WeatherPlugin : public Plugin
{
private:
  unsigned long lastUpdate = 0;
  HTTPClient http;
#ifdef ESP32
  WiFiClientSecure *secureClient = nullptr;
  std::atomic<bool> httpInProgress{false};  // Thread-safe flag for HTTP operations
  std::atomic<bool> teardownRequested{false};  // Signal to abort HTTP operations
#endif
#ifdef ESP8266
  WiFiClient wiFiClient;
#endif

  // Cached weather data
  bool hasCachedData = false;
  int cachedTemperature = 0;
  int cachedWeatherIcon = 0;
  int cachedIconY = 1;
  int cachedTempY = 10;

  void drawWeather();
  void showError();
  void cleanupClient();

public:
  ~WeatherPlugin()
  {
#ifdef ESP32
    if (secureClient != nullptr)
    {
      delete secureClient;
      secureClient = nullptr;
    }
#endif
  }

  void update();
  void setup() override;
  void loop() override;
  void teardown() override;
  const char *getName() const override;
};
