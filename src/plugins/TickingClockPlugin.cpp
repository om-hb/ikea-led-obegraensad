#include "plugins/TickingClockPlugin.h"

void TickingClockPlugin::setup()
{
  previousMinutes = -1;
  previousHour = -1;
  previousSecond = -1;
  previousHH.clear();
  previousMM.clear();
}

void TickingClockPlugin::loop()
{
  // Use timeout of 100ms to avoid blocking, NTP sync happens in background
  if (getLocalTime(&timeinfo, 100))
  {
    // NTP recovered from failure - force full redraw
    if (ntpFailed)
    {
      ntpFailed = false;
      previousHH.clear();
      previousMM.clear();
      previousHour = -1;
      previousMinutes = -1;
      previousSecond = -1;
    }

    if (previousHour != timeinfo.tm_hour || previousMinutes != timeinfo.tm_min)
    {

      std::vector<int> hh = {(timeinfo.tm_hour - timeinfo.tm_hour % 10) / 10, timeinfo.tm_hour % 10};
      std::vector<int> mm = {(timeinfo.tm_min - timeinfo.tm_min % 10) / 10, timeinfo.tm_min % 10};

      if (previousHH.empty())
      {
        Screen.clear();
        Screen.drawCharacter(2,
                             0,
                             Screen.readBytes(fonts[1].data[hh[0]]),
                             8,
                             Screen.getCurrentBrightness());
        Screen.drawCharacter(9,
                             0,
                             Screen.readBytes(fonts[1].data[hh[1]]),
                             8,
                             Screen.getCurrentBrightness());
        Screen.drawCharacter(2,
                             9,
                             Screen.readBytes(fonts[1].data[mm[0]]),
                             8,
                             Screen.getCurrentBrightness());
        Screen.drawCharacter(9,
                             9,
                             Screen.readBytes(fonts[1].data[mm[1]]),
                             8,
                             Screen.getCurrentBrightness());
      }
      else
      {
        if (hh[0] != previousHH[0])
        {
          Screen.drawCharacter(2,
                               0,
                               Screen.readBytes(fonts[1].data[hh[0]]),
                               8,
                               Screen.getCurrentBrightness());
        }
        if (hh[1] != previousHH[1])
        {
          Screen.drawCharacter(9,
                               0,
                               Screen.readBytes(fonts[1].data[hh[1]]),
                               8,
                               Screen.getCurrentBrightness());
        }
        if (mm[0] != previousMM[0])
        {
          Screen.drawCharacter(2,
                               9,
                               Screen.readBytes(fonts[1].data[mm[0]]),
                               8,
                               Screen.getCurrentBrightness());
        }
        if (mm[1] != previousMM[1])
        {
          Screen.drawCharacter(9,
                               9,
                               Screen.readBytes(fonts[1].data[mm[1]]),
                               8,
                               Screen.getCurrentBrightness());
        }
      }

      previousHH = hh;
      previousMM = mm;
      previousMinutes = timeinfo.tm_min;
      previousHour = timeinfo.tm_hour;
    }
    if (previousSecond != timeinfo.tm_sec)
    {
      // clear second lane
      Screen.clearRect(0, 7, 16, 2);
      // alternating second pixel
      if ((timeinfo.tm_sec * 32 / 60) % 2 == 0)
        Screen.setPixel(timeinfo.tm_sec * 16 / 60, 7, 1, Screen.getCurrentBrightness());
      else
        Screen.setPixel(timeinfo.tm_sec * 16 / 60, 8, 1, Screen.getCurrentBrightness());

      previousSecond = timeinfo.tm_sec;
    }
  }
  else if (!ntpFailed)
  {
    // NTP sync failed - show X on display
    ntpFailed = true;
    Screen.clear();
    for (int i = 0; i < 8; i++)
    {
      Screen.setPixel(4 + i, 4 + i, 1, 15);
      Screen.setPixel(4 + i, 11 - i, 1, 15);
    }
  }
}

const char *TickingClockPlugin::getName() const
{
  return "Ticking Clock";
}
