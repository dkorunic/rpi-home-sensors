README
======

Collection of my various Raspberry PI tools, hacks and scripts.


rpi-plot.py
-----------

This is a Raspberry PI temperature graphing PoC through PlotLy.

Plots CPU temperature (directly from RPI), environment temperature (BMP085),
environment barometric pressure (BMP085), environment humidity (DHT22). It runs as
a Unix daemon and preferably runs infinitely long.

Hardware requirements:
* Raspberry PI
* dupont cables or cobbler with breadboard (GPIO and I2C)
* BMP085, BMP180, BMP183: https://www.adafruit.com/products/1900
* DHT11, DHT22 or DHT2302: https://www.adafruit.com/products/385

Requirements:
* Raspberry PI model A or B
* WiringPI library: git://git.drogon.net/wiringPi
* bcm2835 library: http://www.airspayce.com/mikem/bcm2835/
* Adafruit BMP085 I2C library: included!
* Adafruit DHT GPIO library: https://github.com/adafruit/Adafruit_Python_DHT
* PlotLy account:  http://plot.ly

Note:
* Raspberry PI model A users need to edit Adafruit_I2C.py and do the following change:

```
    self.bus = smbus.SMBus(0);
```

Snapshot:
![http://raw.githubusercontent.com/dkorunic/rpi-tools/master/rpi-plot.png](http://raw.githubusercontent.com/dkorunic/rpi-tools/master/rpi-plot.png)
