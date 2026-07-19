#include "plugins/WeatherPlugin.h"
#include "config.h"

// https://github.com/chubin/wttr.in/blob/master/share/translations/en.txt
#ifdef ESP32
#include <WiFi.h>
#endif
#ifdef ESP8266
#include <ESP8266WiFi.h>
WiFiClient wiFiClient;
#endif

void WeatherPlugin::setup()
{
  Screen.clear();

#ifdef ESP32
  // Secure client will be created fresh on each update() call
  secureClient = nullptr;
  // Reset teardown flag in case we're being re-activated
  teardownRequested.store(false);
  httpInProgress.store(false);
#endif

  // If we have cached data and it's still fresh (< 30 minutes old), redraw it
  if (hasCachedData && lastUpdate > 0 && millis() >= lastUpdate &&
      millis() - lastUpdate < (1000UL * 60 * 30))
  {
    Serial.println("Using cached weather data");
    drawWeather();
  }
  else
  {
    // Show loading screen - data needs to be fetched
    currentStatus = LOADING;
    Screen.setPixel(4, 7, 1);
    Screen.setPixel(5, 7, 1);
    Screen.setPixel(7, 7, 1);
    Screen.setPixel(8, 7, 1);
    Screen.setPixel(10, 7, 1);
    Screen.setPixel(11, 7, 1);
    currentStatus = NONE;

    // Clear lastUpdate to force immediate fetch on first loop
    this->lastUpdate = 0;
  }
}

void WeatherPlugin::loop()
{
  if (this->lastUpdate == 0 || millis() >= this->lastUpdate + (1000 * 60 * 30))
  {
    this->update();
    this->lastUpdate = millis();
    Serial.println("updating weather");
  };
}

void WeatherPlugin::update()
{
  // Check WiFi connection first
  if (WiFi.status() != WL_CONNECTED)
  {
    Serial.println("[WeatherPlugin] WiFi not connected, skipping weather update");
    return;
  }

#ifdef ESP32
  // Check if teardown was requested before starting
  if (teardownRequested.load())
  {
    Serial.println("[WeatherPlugin] Teardown requested, aborting update");
    return;
  }
  httpInProgress.store(true);
#endif

  String weatherLocation = config.getWeatherLocation();
  Serial.print("[WeatherPlugin] Fetching weather for: ");
  Serial.println(weatherLocation);
  Serial.printf("[WeatherPlugin] Free heap: %d bytes\n", ESP.getFreeHeap());

#ifdef ESP32
  // Create secure client
  if (secureClient != nullptr)
  {
    delete secureClient;
  }
  secureClient = new WiFiClientSecure();
  secureClient->setInsecure();
  secureClient->setTimeout(10);
#endif

  // Step 1: Geocode the city name using Open-Meteo
  String geoUrl = "https://geocoding-api.open-meteo.com/v1/search?name=" + weatherLocation + "&count=1&language=en&format=json";
  Serial.print("[WeatherPlugin] Geocoding URL: ");
  Serial.println(geoUrl);

#ifdef ESP32
  http.begin(*secureClient, geoUrl);
#endif
#ifdef ESP8266
  http.begin(wiFiClient, geoUrl);
#endif

  http.setTimeout(10000);
  int code = http.GET();

#ifdef ESP32
  // Check if teardown was requested during HTTP request
  if (teardownRequested.load())
  {
    Serial.println("[WeatherPlugin] Teardown requested during geocoding, cleaning up");
    http.end();
    cleanupClient();
    httpInProgress.store(false);
    return;
  }
#endif

  if (code != HTTP_CODE_OK)
  {
    Serial.printf("[WeatherPlugin] Geocoding failed with code: %d\n", code);
    showError();
    http.end();
    cleanupClient();
#ifdef ESP32
    httpInProgress.store(false);
#endif
    return;
  }

  String geoPayload = http.getString();
  http.end();

  JsonDocument geoDoc;
  DeserializationError geoError = deserializeJson(geoDoc, geoPayload);
  if (geoError || !geoDoc["results"][0])
  {
    Serial.println("[WeatherPlugin] Geocoding parse failed or no results");
    showError();
    cleanupClient();
#ifdef ESP32
    httpInProgress.store(false);
#endif
    return;
  }

  float lat = geoDoc["results"][0]["latitude"].as<float>();
  float lon = geoDoc["results"][0]["longitude"].as<float>();
  Serial.printf("[WeatherPlugin] Coordinates: %.2f, %.2f\n", lat, lon);

#ifdef ESP32
  // Check if teardown was requested before second request
  if (teardownRequested.load())
  {
    Serial.println("[WeatherPlugin] Teardown requested, aborting before weather fetch");
    cleanupClient();
    httpInProgress.store(false);
    return;
  }
#endif

  // Step 2: Get weather from Open-Meteo
  String weatherUrl = "https://api.open-meteo.com/v1/forecast?latitude=" + String(lat, 2) +
                      "&longitude=" + String(lon, 2) +
                      "&current=temperature_2m,weather_code&timezone=auto";
  Serial.print("[WeatherPlugin] Weather URL: ");
  Serial.println(weatherUrl);

#ifdef ESP32
  http.begin(*secureClient, weatherUrl);
#endif
#ifdef ESP8266
  http.begin(wiFiClient, weatherUrl);
#endif

  http.setTimeout(10000);
  code = http.GET();
  Serial.printf("[WeatherPlugin] Weather response code: %d\n", code);

#ifdef ESP32
  // Check if teardown was requested during HTTP request
  if (teardownRequested.load())
  {
    Serial.println("[WeatherPlugin] Teardown requested during weather fetch, cleaning up");
    http.end();
    cleanupClient();
    httpInProgress.store(false);
    return;
  }
#endif

  if (code == HTTP_CODE_OK)
  {
    String payload = http.getString();
    Serial.printf("[WeatherPlugin] Response size: %d bytes\n", payload.length());

    JsonDocument doc;
    DeserializationError error = deserializeJson(doc, payload);

    if (error)
    {
      Serial.print("[WeatherPlugin] JSON parsing failed: ");
      Serial.println(error.c_str());
      http.end();
      cleanupClient();
#ifdef ESP32
      httpInProgress.store(false);
#endif
      return;
    }

    int temperature = round(doc["current"]["temperature_2m"].as<float>());
    int weatherCode = doc["current"]["weather_code"].as<int>();
    Serial.printf("[WeatherPlugin] Temperature: %d°C, WMO Code: %d\n", temperature, weatherCode);

    // Map WMO weather codes to icons
    // WMO codes: https://open-meteo.com/en/docs
    int weatherIcon = 0;
    int iconY = 1;
    int tempY = 10;

    if (weatherCode >= 95)  // Thunderstorm
    {
      weatherIcon = 1;
    }
    else if (weatherCode >= 80 || (weatherCode >= 51 && weatherCode <= 67))  // Rain/Drizzle/Showers
    {
      weatherIcon = 4;
    }
    else if (weatherCode >= 71 && weatherCode <= 77)  // Snow
    {
      weatherIcon = 5;
    }
    else if (weatherCode >= 45 && weatherCode <= 48)  // Fog
    {
      weatherIcon = 6;
      iconY = 2;
    }
    else if (weatherCode == 0)  // Clear sky
    {
      weatherIcon = 2;
      iconY = 1;
      tempY = 9;
    }
    else if (weatherCode == 3)  // Overcast
    {
      weatherIcon = 0;
      iconY = 2;
      tempY = 9;
    }
    else if (weatherCode >= 1 && weatherCode <= 2)  // Partly cloudy
    {
      weatherIcon = 3;
      iconY = 2;
    }

    // Cache the weather data
    hasCachedData = true;
    cachedTemperature = temperature;
    cachedWeatherIcon = weatherIcon;
    cachedIconY = iconY;
    cachedTempY = tempY;

    // Draw the weather (only if not tearing down)
#ifdef ESP32
    if (!teardownRequested.load())
    {
      drawWeather();
    }
#else
    drawWeather();
#endif
  }
  else
  {
    Serial.printf("[WeatherPlugin] Weather request failed with code: %d\n", code);
    showError();
  }

  http.end();
  cleanupClient();
#ifdef ESP32
  httpInProgress.store(false);
#endif
}

void WeatherPlugin::showError()
{
  if (!hasCachedData)
  {
    Screen.clear();
    // Draw exclamation mark
    Screen.setPixel(7, 4, 1);
    Screen.setPixel(8, 4, 1);
    Screen.setPixel(7, 5, 1);
    Screen.setPixel(8, 5, 1);
    Screen.setPixel(7, 6, 1);
    Screen.setPixel(8, 6, 1);
    Screen.setPixel(7, 7, 1);
    Screen.setPixel(8, 7, 1);
    Screen.setPixel(7, 8, 1);
    Screen.setPixel(8, 8, 1);
    Screen.setPixel(7, 10, 1);
    Screen.setPixel(8, 10, 1);
    Screen.setPixel(7, 11, 1);
    Screen.setPixel(8, 11, 1);
  }
  else
  {
    Serial.println("[WeatherPlugin] Using cached data instead");
    drawWeather();
  }
}

void WeatherPlugin::cleanupClient()
{
#ifdef ESP32
  if (secureClient != nullptr)
  {
    delete secureClient;
    secureClient = nullptr;
  }
#endif
}

void WeatherPlugin::teardown()
{
#ifdef ESP32
  // Signal any in-progress HTTP operations to abort
  teardownRequested.store(true);

  // If HTTP operations are in progress, don't touch anything
  // The update() function runs on a different core and will handle cleanup
  // when it sees teardownRequested flag
  if (httpInProgress.load())
  {
    Serial.println("[WeatherPlugin] HTTP in progress, deferring cleanup to update()");
    // Do NOT call http.end() or cleanupClient() here!
    // The secureClient is still being used by HTTPClient on Core 0
    // Let the update() function clean up when it finishes
  }
  else
  {
    // No HTTP in progress, safe to call http.end()
    http.end();
    cleanupClient();
  }
  // Note: Don't reset teardownRequested here - update() needs to see it
#else
  http.end();
#endif
}

void WeatherPlugin::drawWeather()
{
  Screen.clear();
  Screen.drawWeather(0, cachedIconY, cachedWeatherIcon, 100);

  int temperature = cachedTemperature;
  int tempY = cachedTempY;

  if (temperature >= 10)
  {
    Screen.drawCharacter(9, tempY, Screen.readBytes(degreeSymbol), 4, 50);
    Screen.drawNumbers(1, tempY, {(temperature - temperature % 10) / 10, temperature % 10});
  }
  else if (temperature <= -10)
  {
    Screen.drawCharacter(0, tempY, Screen.readBytes(minusSymbol), 4);
    Screen.drawCharacter(11, tempY, Screen.readBytes(degreeSymbol), 4, 50);
    temperature *= -1;
    Screen.drawNumbers(3, tempY, {(temperature - temperature % 10) / 10, temperature % 10});
  }
  else if (temperature >= 0)
  {
    Screen.drawCharacter(7, tempY, Screen.readBytes(degreeSymbol), 4, 50);
    Screen.drawNumbers(4, tempY, {temperature});
  }
  else
  {
    Screen.drawCharacter(0, tempY, Screen.readBytes(minusSymbol), 4);
    Screen.drawCharacter(9, tempY, Screen.readBytes(degreeSymbol), 4, 50);
    Screen.drawNumbers(3, tempY, {-temperature});
  }
}

const char *WeatherPlugin::getName() const
{
  return "Weather";
}
