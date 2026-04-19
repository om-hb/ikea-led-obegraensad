#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>
#include <string>
#include <vector>

#include "screen.h"
#include "signs.h"
#include "websocket.h"

class Plugin
{
private:
  int id;

public:
  Plugin();

  virtual ~Plugin()
  {
  }

  virtual void teardown();
  virtual void websocketHook(JsonDocument &request);
  virtual void setup() = 0;
  virtual void loop();
  virtual const char *getName() const = 0;

  void setId(int id);
  int getId() const;
};

class PluginManager
{
private:
  std::vector<Plugin *> plugins;
  Plugin *activePlugin = nullptr;
  int nextPluginId;
  int persistedPluginId = 1;
  volatile int pendingPluginId = -1;  // For async plugin switching

  void renderPluginId(int pluginId);

public:
  PluginManager();

  int addPlugin(Plugin *plugin);
  void setActivePlugin(const char *pluginName);
  void setActivePluginById(int pluginId);
  void requestPluginById(int pluginId);  // Non-blocking request for async contexts
  void processPendingPluginChange();     // Called from main task to apply pending change
  void runActivePlugin();
  void setupActivePlugin();
  void activateNextPlugin();
  void persistActivePlugin();
  void init();
  void activatePersistedPlugin();
  int getPersistedPluginId();
  Plugin *getActivePlugin() const;
  std::vector<Plugin *> &getAllPlugins();
  size_t getNumPlugins();
};

extern PluginManager pluginManager;
