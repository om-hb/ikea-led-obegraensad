#include "plugins/BigClockPlugin.h"

void BigClockPlugin::setup()
{
  // loading screen
  Screen.setPixel(4, 7, 1);
  Screen.setPixel(5, 7, 1);
  Screen.setPixel(7, 7, 1);
  Screen.setPixel(8, 7, 1);
  Screen.setPixel(10, 7, 1);
  Screen.setPixel(11, 7, 1);

  previousMinutes = -1;
  previousHour = -1;
  previousHH.clear();
  previousMM.clear();
  previousLeadingZero = false;
}

void BigClockPlugin::loop()
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
    }

    if (previousHour != timeinfo.tm_hour || previousMinutes != timeinfo.tm_min)
    {
      std::vector<int> hh = {(timeinfo.tm_hour - timeinfo.tm_hour % 10) / 10, timeinfo.tm_hour % 10};
      std::vector<int> mm = {(timeinfo.tm_min - timeinfo.tm_min % 10) / 10, timeinfo.tm_min % 10};
      bool leadingZero = (hh.at(0) == 0);

      bool layoutChanged = (previousHH.empty() || previousLeadingZero != leadingZero);

      if (layoutChanged)
      {

        Screen.clear();
        if (leadingZero)
        {
          hh.erase(hh.begin());
          Screen.drawBigNumbers(COLS / 2, 0, hh);
          Screen.drawBigNumbers(0, ROWS / 2, mm);
        }
        else
        {
          Screen.drawBigNumbers(0, 0, hh);
          Screen.drawBigNumbers(0, ROWS / 2, mm);
        }
      }
      else
      {

        std::vector<int> displayHH = hh;
        if (leadingZero)
        {
          displayHH.erase(displayHH.begin());
        }

        if (displayHH != previousHH)
        {
          int startX = leadingZero ? COLS / 2 : 0;
          Screen.drawBigNumbers(startX, 0, displayHH);
        }

        if (mm != previousMM)
        {
          Screen.drawBigNumbers(0, ROWS / 2, mm);
        }

        previousHH = displayHH;
        previousMM = mm;
      }

      if (layoutChanged)
      {

        std::vector<int> displayHH = hh;
        if (leadingZero)
        {
          displayHH.erase(displayHH.begin());
        }
        previousHH = displayHH;
        previousMM = mm;
      }

      previousMinutes = timeinfo.tm_min;
      previousHour = timeinfo.tm_hour;
      previousLeadingZero = leadingZero;
    }
  }
  else if (!ntpFailed)
  {
    // NTP sync failed - show X on display
    ntpFailed = true;
    Screen.clear();
    // Draw X in center of display
    for (int i = 0; i < 8; i++)
    {
      Screen.setPixel(4 + i, 4 + i, 1, 15);
      Screen.setPixel(4 + i, 11 - i, 1, 15);
    }
  }
}

const char *BigClockPlugin::getName() const
{
  return "Big Clock";
}
