#!/usr/bin/env python
# -*- coding: iso-8859-1 -*-

"""Raspberry PI temperature graphing PoC through PlotLy

   Plots CPU temperature (directly from RPI), environment temperature (BMP085),
   environment barometric pressure (BMP085), environment humidity (DHT22).

   Hardware requirements:
   - Raspberry PI
   - dupont cables or cobbler with breadboard (GPIO and I2C)
   - BMP085, BMP180, BMP183: https://www.adafruit.com/products/1900
   - DHT11, DHT22 or DHT2302: https://www.adafruit.com/products/385

   Requirements:
   - Raspberry PI model A or B
   - WiringPI library: git://git.drogon.net/wiringPi
   - bcm2835 library: http://www.airspayce.com/mikem/bcm2835/
   - Adafruit BMP085 I2C library: included!
   - Adafruit DHT GPIO library: https://github.com/adafruit/Adafruit_Python_DHT
   - PlotLy account:  http://plot.ly
"""

import time
import datetime
import sys

import Adafruit_DHT
import Adafruit_BMP085
import daemon
import plotly.plotly as py
import plotly.tools as tls
from plotly.graph_objs import Data, Layout, Figure, Stream, Scatter, YAxis, XAxis, Font


DHT_VER = 22  # 11, 22 or 2302
DHT_GPIO = 4  # any connected GPIO
BMP085_ADDRESS = 0x77  # I2C address
BMP085_MODE = 1  # 0 = ULTRALOWPOWER, 1 = STANDARD, 2 = HIRES, 3 = ULTRAHIRES

SLEEP_DELAY = 300  # poll delay
PLOTLY_CHART_NAME = 'Raspberry PI'  # graph title
MAX_POINTS = 300  # graph data points
GRAPH_MODE = 'lines+markers'


def read_cpu():
    cpu_temp = 50.0
    try:
        cpu_temp = float(open('/sys/class/thermal/thermal_zone0/temp').read()) / 1000.
    except:
        pass

    return cpu_temp


def plot_data(debug=False):
    # pull in PlotLy authentication data
    plotly_creds = tls.get_credentials_file()
    username = plotly_creds['username']
    api_key = plotly_creds['api_key']
    token_cpu, token_temp, token_humidity, token_pressure = plotly_creds['stream_ids'][0:4]

    py.sign_in(username, api_key)

    # create Stream objects with proper tokens and maximum preserved graph points
    my_stream_cpu = Stream(token=token_cpu, maxpoints=MAX_POINTS)
    my_stream_temp = Stream(token=token_temp, maxpoints=MAX_POINTS)
    my_stream_humidity = Stream(token=token_humidity, maxpoints=MAX_POINTS)
    my_stream_pressure = Stream(token=token_pressure, maxpoints=MAX_POINTS)

    # create Scatter-type graphs with appropriate names; don't provide sample data as we'll provide it live in
    # Stream mode
    my_scatter_cpu = Scatter(x=[], y=[], stream=my_stream_cpu, name='CPU temperature', mode=GRAPH_MODE)
    my_scatter_temp = Scatter(x=[], y=[], stream=my_stream_temp,
                              name='Environment temperature', mode=GRAPH_MODE)
    my_scatter_humidity = Scatter(x=[], y=[], stream=my_stream_humidity,
                                  name='Environment Humidity', mode=GRAPH_MODE)
    my_scatter_pressure = Scatter(x=[], y=[], stream=my_stream_pressure,
                                  name='Barometric pressure', yaxis='y2',
                                  mode=GRAPH_MODE)

    my_data = Data([my_scatter_cpu, my_scatter_temp, my_scatter_humidity,
                    my_scatter_pressure])

    # create Layout where we have one shared X axis (time series) and two Y axis, one left (temperature and humidity)
    # and one right (pressure)
    my_layout = Layout(title='Raspberry PI Sensors',
                       xaxis=XAxis(title='Time'), yaxis=YAxis(title='Temperature [C] / Humidity [%]'),
                       yaxis2=YAxis(title='Pressure [hPa]',
                                    overlaying='y', side='right',
                                    titlefont=Font(color='rgb(148, 103, 189)'),
                                    tickfont=Font(color='rgb(148, 103, 189)')))

    my_fig = Figure(data=my_data, layout=my_layout)

    # overwrite existing data on creating the new figure
    py.plot(my_fig, filename=PLOTLY_CHART_NAME, auto_open=False, fileopt='overwrite')

    # initialize BMP085 or any of compatible equivalents
    bmp = Adafruit_BMP085.BMP085(BMP085_ADDRESS, BMP085_MODE)

    # initialize Streams with different stream ids, so that each has its own trace
    s_cpu = py.Stream(token_cpu)
    s_temp = py.Stream(token_temp)
    s_humidity = py.Stream(token_humidity)
    s_pressure = py.Stream(token_pressure)

    s_cpu.open()
    s_temp.open()
    s_humidity.open()
    s_pressure.open()

    while True:
        try:
            # gather data
            cpu_temp = read_cpu()
            dht_hum, dht_temp = Adafruit_DHT.read_retry(DHT_VER, DHT_GPIO)
            bmp_temp = bmp.readTemperature()
            bmp_pres = bmp.readPressure() / 100.0

            date_stamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')

            if debug:
                print 'Timestamp: %s' % date_stamp
                print 'CPU Temp: %.2f �C' % cpu_temp
                print 'DHT Humidity: %.2f %%' % dht_hum
                print 'DHT Temperature: %.2f �C' % dht_temp
                print 'BMP Temperature: %.2f �C' % bmp_temp
                print 'BMP Pressure: %.2f hPa' % bmp_pres

            # push data to PlotLy
            s_cpu.write(dict(x=date_stamp, y=cpu_temp))
            s_temp.write(dict(x=date_stamp, y=bmp_temp))
            s_humidity.write(dict(x=date_stamp, y=dht_hum))
            s_pressure.write(dict(x=date_stamp, y=bmp_pres))

            time.sleep(SLEEP_DELAY)
        finally:
            s_cpu.close()
            s_temp.close()
            s_humidity.close()
            s_pressure.close()


def run():
    my_daemon = True
    my_debug = False

    if 'nodaemon' in sys.argv:
        my_daemon = False
    if 'debug' in sys.argv:
        my_debug = True
        my_daemon = False

    # preferably daemonize
    if my_daemon:
        with daemon.DaemonContext():
            plot_data(my_debug)
    else:
        plot_data(my_debug)


if __name__ == '__main__':
    run()
