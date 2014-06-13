#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Raspberry PI temperature graphing PoC through PlotLy

   Plots CPU temperature (directly from RPI), environment temperature (BMP085),
   environment barometric pressure (BMP085), environment humidity (DHT22). It runs as
   a Unix daemon and preferably runs infinitely long.

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
   - PlotLy library: pip install plotly
   - daemon library: pip install daemon

   Note:
   - Raspberry PI model A users need to edit Adafruit_I2C.py and do the following change:
   self.bus = smbus.SMBus(0);
"""

__copyright__ = """Copyright (C) 2014  Dinko Korunic <dinko.korunic@gmail.com>

This program is free software; you can redistribute it and/or modify it
under the terms of the GNU General Public License as published by the
Free Software Foundation; either version 2 of the License, or (at your
option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License along
with this program; if not, write to the Free Software Foundation, Inc.,
59 Temple Place, Suite 330, Boston, MA  02111-1307 USA
"""

import time
import datetime
import sys
import os
import socket

import Adafruit_DHT
import Adafruit_BMP085
import daemon
import plotly.exceptions
import plotly.plotly
import plotly.tools
from plotly.graph_objs import Data, Layout, Figure, Stream, Scatter, YAxis, XAxis, Font


DHT_VER = 22  # 11, 22 or 2302
DHT_GPIO = 4  # any connected GPIO
BMP085_ADDRESS = 0x77  # I2C address
BMP085_MODE = 1  # 0 = ULTRALOWPOWER, 1 = STANDARD, 2 = HIRES, 3 = ULTRAHIRES

SLEEP_DELAY = 300  # poll delay
PLOTLY_CHART_NAME = 'Raspberry PI'  # graph title
MAX_POINTS = 300  # graph data points
GRAPH_MODE = 'lines'  # lines or lines+markers trace type


def backoff_sleep(reset=False, delay=2, max_delay=1024, debug=False):
    """
    Sleep function with exponential backoff with deterministic maximum and option to reset delay to default.

    :param reset: Resets the next run to default delay without backoff
    :param delay: Initial backoff delay
    :param max_delay: Maximal backoff after which delay becomes constant
    :param debug: In debug mode it displays the amount of backoff seconds done
    """
    global _backoff_delay

    if reset:
        _backoff_delay = None
    else:
        if not '_backoff_delay' in globals() or _backoff_delay is None:
            _backoff_delay = delay

        if debug:
            print >> sys.stderr, 'INFO: Backoff initiated in the duration %d seconds.' % _backoff_delay
        time.sleep(_backoff_delay)

        _backoff_delay *= 2
        if _backoff_delay > max_delay:
            _backoff_delay = max_delay


def read_rpi_cpu():
    """
    Fetch temperature from CPU0 thermal zone from /proc file and return float.
    """
    try:
        tz_file = open('/sys/class/thermal/thermal_zone0/temp')
        try:
            cpu_temp = float(tz_file.read()) / 1000.
        finally:
            tz_file.close()
    except IOError, msg:
        raise RuntimeError(msg)

    return cpu_temp


def init_bmp():
    """
    Initializes BMP085, BMP180 or BMP183 devices.
    """
    try:

        bmp = Adafruit_BMP085.BMP085(BMP085_ADDRESS, BMP085_MODE)
    except IOError:
        print >> sys.stderr, 'ERROR: I2C BMP085 reading failure.'
        sys.exit(1)

    return bmp


def init_plotly():
    """
    Prepares authenticate tokens for each trace, prepares layout and streams with corresponding scatter graph traces.
    """
    # pull in PlotLy authentication data
    plotly_creds = plotly.tools.get_credentials_file()
    username = plotly_creds['username']
    api_key = plotly_creds['api_key']
    token_cpu, token_temp, token_humidity, token_pressure = plotly_creds['stream_ids'][0:4]

    plotly.plotly.sign_in(username, api_key)

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
                                  name='Environment humidity', mode=GRAPH_MODE)
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
    plotly.plotly.plot(my_fig, filename=PLOTLY_CHART_NAME, auto_open=False, fileopt='overwrite')

    # initialize Streams with different stream ids, so that each has its own trace
    s_cpu = plotly.plotly.Stream(token_cpu)
    s_temp = plotly.plotly.Stream(token_temp)
    s_humidity = plotly.plotly.Stream(token_humidity)
    s_pressure = plotly.plotly.Stream(token_pressure)

    return s_cpu, s_humidity, s_pressure, s_temp


def plot_data(debug=False):
    """
    Gather all data from DHT and BMP sensors and graph on PlotLy. Tries to be resilient to most intermittent
    errors.

    :param debug: Control of verbose sensor readouts
    """
    bmp = init_bmp()
    s_cpu, s_humidity, s_pressure, s_temp = init_plotly()

    while True:
        try:
            s_cpu.open()
            s_temp.open()
            s_humidity.open()
            s_pressure.open()
        except socket.error:
            if debug:
                print >> sys.stderr, 'ERROR: socket error connecting to PlotLy. Retrying...'
            backoff_sleep(delay=60, debug=debug)

        while True:
            try:
                # gather data
                try:
                    cpu_temp = read_rpi_cpu()
                except RuntimeError:
                    if debug:
                        print >> sys.stderr, 'ERROR: CPU0 thermal zone reading failure.'
                    sys.exit(1)

                try:
                    dht_hum, dht_temp = Adafruit_DHT.read_retry(DHT_VER, DHT_GPIO)
                except RuntimeError:
                    if debug:
                        print >> sys.stderr, 'ERROR: GPIO DHT reading failure.'
                    sys.exit(1)

                try:
                    bmp_temp = bmp.readTemperature()
                    bmp_pres = bmp.readPressure() / 100.0
                except IOError:
                    if debug:
                        print >> sys.stderr, 'ERROR: I2C BMP085 reading failure.'
                    sys.exit(1)

                date_stamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')

                if debug:
                    print 'Timestamp: %s' % date_stamp
                    print 'CPU Temp: %.2f ºC' % cpu_temp
                    print 'DHT Humidity: %.2f %%' % dht_hum
                    print 'DHT Temperature: %.2f ºC' % dht_temp
                    print 'BMP Temperature: %.2f ºC' % bmp_temp
                    print 'BMP Pressure: %.2f hPa' % bmp_pres
                    print 40 * '-'

                try:
                    # push data to PlotLy
                    s_cpu.write(dict(x=date_stamp, y=cpu_temp))
                    s_temp.write(dict(x=date_stamp, y=bmp_temp))
                    s_humidity.write(dict(x=date_stamp, y=dht_hum))
                    s_pressure.write(dict(x=date_stamp, y=bmp_pres))

                    backoff_sleep(reset=True)
                    time.sleep(SLEEP_DELAY)
                except (IOError, socket.error, plotly.exceptions.PlotlyError):
                    if debug:
                        print >> sys.stderr, 'ERROR: socket error writing to PlotLy. Retrying...'
                    backoff_sleep(delay=60, debug=debug)
                    break

            finally:
                try:
                    s_cpu.close()
                    s_temp.close()
                    s_humidity.close()
                    s_pressure.close()
                except plotly.exceptions.PlotlyError:
                    pass


def run():
    my_daemon = True
    my_debug = False

    if 'nodaemon' in sys.argv:
        my_daemon = False
    if 'debug' in sys.argv:
        my_debug = True
        my_daemon = False

    if os.geteuid() != 0:
        print >> sys.stderr, 'ERROR: You need root to be able to read GPIO, I2C and CPU thermal zones.'
        sys.exit(1)

    # preferably daemonize
    if my_daemon:
        with daemon.DaemonContext():
            plot_data(my_debug)
    else:
        plot_data(my_debug)


if __name__ == '__main__':
    run()
