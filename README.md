README
======

This is a Raspberry Pi temperature graphing PoC through Plotly (usually up
to 200 points drawn) and persistant storage through Google Docs
(Spreadsheet).

Plots CPU temperature (directly from RPI), environment temperature
(BMP085), environment barometric pressure (BMP085), environment humidity
(DHT22).  and outdoor temperature (Weather Underground). It runs as a Unix
daemon and preferably runs infinitely long.

If there is a LED available, it will pulse it in the background to indicate its
running status.


Hardware requirements
---------------------
* Raspberry Pi model A or B: http://shop.pimoroni.com/
* dupont cables or cobbler with breadboard (GPIO and I2C):
  http://www.smart-elex.co.uk/RaspberryPi/RASPBERRY-Pi-GPIO-ACCESSORIES/RPI-Electronics-kit1
* BMP085, BMP180, BMP183: https://www.adafruit.com/products/1900
* DHT11, DHT22 or DHT2302: https://www.adafruit.com/products/385
* LED
* 10kOhm and 330Ohm resistors (for DHT and LED)

Software Requirements
---------------------
* Weather Underground developer account (free!): http://www.wunderground.com/weather/api
* Plotly account (free!): http://plot.ly
* Google Docs account (optional)
* WiringPI library: git://git.drogon.net/wiringPi
* bcm2835 library: http://www.airspayce.com/mikem/bcm2835/
* Adafruit BMP085 I2C library: included!
* Adafruit DHT GPIO library: https://github.com/adafruit/Adafruit_Python_DHT
* Plotly library: pip install plotly
* daemon library: pip install daemon

Important notes
---------------
* Raspberry PI model A users need to edit Adafruit_I2C.py and do the following change:

```
    self.bus = smbus.SMBus(0);
```

* You can store Weather Underground configuration in /root/.weather_underground.rc:

```
   {"wu_city": "Zagreb", "wu_state": "Croatia", "wu_key": "XXXX"}
```

Snapshot
--------
![/rpi-plot.png](/rpi-plot.png)
![/rpi-board.png](/rpi-board.png)

Copyright
---------
Copyright (C) 2014  Dinko Korunic <dinko.korunic@gmail.com>
