#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Raspberry Pi temperature graphing PoC through Plotly (usually up
   to 200 points drawn) and persistant storage through Google Docs
   (Spreadsheet).

   Plots CPU temperature (directly from RPI), environment temperature
   (BMP085), environment barometric pressure (BMP085), environment humidity
   (DHT22).  and outdoor temperature (Weather Underground). It runs as a Unix
   daemon and preferably runs infinitely long.

   If there is a LED available, it will pulse it in the background to indicate its
   running status.

   Hardware requirements:
   - Raspberry Pi model A or B: http://shop.pimoroni.com/
   - dupont cables or cobbler with breadboard (GPIO and I2C):
     http://www.smart-elex.co.uk/RaspberryPi/RASPBERRY-Pi-GPIO-ACCESSORIES/RPI-Electronics-kit1
   - BMP085, BMP180, BMP183: https://www.adafruit.com/products/1900
   - DHT11, DHT22 or DHT2302: https://www.adafruit.com/products/385
   - LED
   - 10kOhm and 330Ohm resistors (for DHT and LED)

   Software Requirements:
   - Weather Underground developer account (free!): http://www.wunderground.com/weather/api
   - Google Docs account (optional)
   - Plotly account (free!): http://plot.ly
   - WiringPI library: git://git.drogon.net/wiringPi
   - bcm2835 library: http://www.airspayce.com/mikem/bcm2835/
   - Adafruit BMP085 I2C library: included!
   - Adafruit DHT GPIO library: https://github.com/adafruit/Adafruit_Python_DHT
   - Plotly library: pip install plotly
   - daemon library: pip install daemon
   - gspread library: pip install gspread

   Important notes:
   - Raspberry PI model A users need to edit Adafruit_I2C.py and do the following change:

   self.bus = smbus.SMBus(0);

   - You can store Weather Underground configuration in /root/.weather_underground.rc:

   {"wu_city": "Zagreb", "wu_state": "Croatia", "wu_key": "XXXX"}

   - Plotly configuration needs to be stored in /root/.plotly/.credentials

   - You can store Google Docs configuration in /root/.google_docs.rc

   {"gdocs_email": "somebody@gmail.com", "gdocs_password": "secret password", "gdocs_sheet": "somesheet"}
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
import json
import urllib2
import atexit
import threading
import signal
import logging
import Queue

import requests.exceptions
import gspread
import Adafruit_DHT
import Adafruit_BMP085
import daemon
import plotly.exceptions
import plotly.plotly
import plotly.tools
import RPi.GPIO
from plotly.graph_objs import Data, Layout, Figure, Stream, Scatter, YAxis, XAxis, Font


DHT_VER = 22  # 11, 22 or 2302
DHT_GPIO = 4  # any connected GPIO
BMP085_ADDRESS = 0x77  # I2C address
BMP085_MODE = 1  # 0 = ULTRALOWPOWER, 1 = STANDARD, 2 = HIRES, 3 = ULTRAHIRES
LED_GPIO = 27  # any connected GPIO or None if not used

SLEEP_DELAY = 300  # poll delay (never set this to less than 2 seconds!)
PLOTLY_CHART_NAME = 'Raspberry PI'  # graph title
MAX_POINTS = 300  # graph data points
TRACE_MODE = 'lines'  # lines or lines+markers trace type (recommended lines for a lot of data points)
GRAPH_MODE = 'overwrite'  # append or overwrite previous traces (recommended overwrite)
LED_BLINK = 5  # seconds for background LED pulse

WU_KEY = None
WU_STATE = None
WU_CITY = None
WU_API_URL = 'http://api.wunderground.com/api/'
WU_API_QUERY = '/geolookup/conditions/q/'
WU_FAKE_TEMP = 21.0

GDOCS_EMAIL = None
GDOCS_PASSWORD = None
GDOCS_SHEET = None
GDOCS_SHEET_PATTERN = '%Y-%B'  # Year-Month pattern in naming sheets (one sheet per each month)

DATA_QUEUE = Queue.Queue()


def led_pulse():
    """
    Generic LED pulse thread.
    """
    if not LED_GPIO is None:
        while True:
            RPi.GPIO.output(LED_GPIO, RPi.GPIO.HIGH)
            time.sleep(LED_BLINK)
            RPi.GPIO.output(LED_GPIO, RPi.GPIO.LOW)
            time.sleep(LED_BLINK)


def signal_handler(recvd_signal, stack_frame):
    """
    Generic signal handler routine.

    :param recvd_signal: received signal
    :param stack_frame:  current stack frame
    """
    logger = logging.getLogger(sys._getframe().f_code.co_name)
    logger.warning('Got Ctrl-C from console. Exiting...')
    sys.exit(0)


def init_logging(debug=False):
    """
    Generic logging initializing routine.

    :param debug: allow for verbose debug messages or not
    """
    if debug:
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)-15s %(message)s')
    else:
        logging.basicConfig(level=logging.WARNING, format='%(asctime)-15s %(message)s')


def init_led():
    """
    Initialize GPIO pin dedicated for LED blinking.
    """
    global SLEEP_DELAY
    global LED_BLINK

    if not LED_GPIO is None:
        # initialize GPIO
        RPi.GPIO.setwarnings(False)
        RPi.GPIO.setmode(RPi.GPIO.BCM)
        RPi.GPIO.cleanup()
        RPi.GPIO.setup(LED_GPIO, RPi.GPIO.OUT)

        # calculate blink delay
        if SLEEP_DELAY < LED_BLINK:
            LED_BLINK = SLEEP_DELAY >> 1

        # start LED pulsing thread as daemon (will exit automatically)
        t = threading.Thread(target=led_pulse)
        t.daemon = True
        t.start()


@atexit.register
def uninit_led():
    """
    Uninitialize all GPIO pins which might have been used.
    """
    if not LED_GPIO is None:
        RPi.GPIO.cleanup()


def init_bmp():
    """
    Initializes BMP085, BMP180 or BMP183 devices.

    :return: Returns initialized BMP085 device structure
    """
    logger = logging.getLogger(sys._getframe().f_code.co_name)

    try:

        bmp = Adafruit_BMP085.BMP085(BMP085_ADDRESS, BMP085_MODE)
    except IOError, e:
        logger.error('I2C BMP085 reading failure: %s' % e)
        sys.exit(1)

    return bmp


def init_plotly():
    """
    Prepares authenticate tokens for each trace, prepares layout and streams with corresponding scatter graph traces.

    :return: Returns initialized stream IDs for each trace
    """
    logger = logging.getLogger(sys._getframe().f_code.co_name)

    # pull in Plotly authentication data
    plotly_creds = plotly.tools.get_credentials_file()
    username = plotly_creds['username']
    api_key = plotly_creds['api_key']
    token_cpu, token_temp, token_humidity, token_pressure, token_wu = plotly_creds['stream_ids'][0:5]

    plotly.plotly.sign_in(username, api_key)

    # create Stream structures with proper tokens and maximum preserved graph points
    my_stream_cpu = Stream(token=token_cpu, maxpoints=MAX_POINTS)
    my_stream_temp = Stream(token=token_temp, maxpoints=MAX_POINTS)
    my_stream_humidity = Stream(token=token_humidity, maxpoints=MAX_POINTS)
    my_stream_pressure = Stream(token=token_pressure, maxpoints=MAX_POINTS)
    my_stream_wu = Stream(token=token_wu, maxpoints=MAX_POINTS)

    # create Scatter-type structures with appropriate names; don't provide sample data as we'll provide it live in
    # Stream mode
    my_scatter_cpu = Scatter(x=[], y=[], stream=my_stream_cpu, name='CPU temperature', mode=TRACE_MODE)
    my_scatter_temp = Scatter(x=[], y=[], stream=my_stream_temp,
                              name='Environment temperature', mode=TRACE_MODE)
    my_scatter_humidity = Scatter(x=[], y=[], stream=my_stream_humidity,
                                  name='Environment humidity', mode=TRACE_MODE)
    my_scatter_pressure = Scatter(x=[], y=[], stream=my_stream_pressure,
                                  name='Barometric pressure', yaxis='y2',
                                  mode=TRACE_MODE)
    my_scatter_wu = Scatter(x=[], y=[], stream=my_stream_wu, name='Outdoor temperature (Weather Underground)',
                            mode=TRACE_MODE)

    # prepare Data structure
    my_data = Data([my_scatter_cpu, my_scatter_temp, my_scatter_humidity,
                    my_scatter_pressure, my_scatter_wu])

    # create Layout structure where we have one shared X axis (time series) and two Y axis, one left side (temperature
    # and humidity) and one right side (pressure)
    my_layout = Layout(title='Raspberry PI Sensors',
                       xaxis=XAxis(title='Time'), yaxis=YAxis(title='Temperature [C] / Humidity [%]'),
                       yaxis2=YAxis(title='Pressure [hPa]',
                                    overlaying='y', side='right',
                                    titlefont=Font(color='rgb(148, 103, 189)'),
                                    tickfont=Font(color='rgb(148, 103, 189)')))

    # prepare Figure structure
    my_fig = Figure(data=my_data, layout=my_layout)

    try:
        # overwrite existing data on creating the new figure
        plotly.plotly.plot(my_fig, filename=PLOTLY_CHART_NAME, auto_open=False, fileopt=GRAPH_MODE)
    except requests.exceptions.ConnectionError, e:
        logger.error('Cannot connect to PlotLy to create chart: %s. Exiting...' % e)
        sys.exit(1)

    # initialize Stream structures with different stream ids, so that each has its own trace
    s_cpu = plotly.plotly.Stream(token_cpu)
    s_temp = plotly.plotly.Stream(token_temp)
    s_humidity = plotly.plotly.Stream(token_humidity)
    s_pressure = plotly.plotly.Stream(token_pressure)
    s_wu = plotly.plotly.Stream(token_wu)

    return s_cpu, s_humidity, s_pressure, s_temp, s_wu


def init_gdocs():
    """
    Initialize Google Docs globals from $HOME/.google_docs.rc JSON if it exists.
    """
    global GDOCS_EMAIL
    global GDOCS_PASSWORD
    global GDOCS_SHEET

    logger = logging.getLogger(sys._getframe().f_code.co_name)

    # XXX: use argument parser for this
    gdocs_file = ''.join([os.environ['HOME'], os.sep, '.google_docs.rc'])

    try:
        f = open(gdocs_file)

        try:
            json_string = f.read()
            try:
                parsed_json = json.loads(json_string)

                if 'gdocs_email' in parsed_json:
                    GDOCS_EMAIL = parsed_json['gdocs_email']
                if 'gdocs_password' in parsed_json:
                    GDOCS_PASSWORD = parsed_json['gdocs_password']
                if 'gdocs_sheet' in parsed_json:
                    GDOCS_SHEET = parsed_json['gdocs_sheet']
            except ValueError, e:
                logger.warning('Invalid Google Docs JSON configuration in %s: %s' % (gdocs_file, e))
                pass
        finally:
            f.close()
    except IOError, e:
        logger.warning('Could not open/read Google Docs configuration in %s: %s' % (gdocs_file, e))


def init_weather_underground():
    """
    Initialize Weather Undeground API from either globals or $HOME/.weather_underground.rc JSON with later one
    being preferred.

    :return: returns full Weather Underground API URL
    """
    global WU_KEY
    global WU_STATE
    global WU_CITY

    logger = logging.getLogger(sys._getframe().f_code.co_name)

    # XXX: use argument parser for this
    wu_file = ''.join([os.environ['HOME'], os.sep, '.weather_underground.rc'])

    try:
        f = open(wu_file)

        try:
            json_string = f.read()
            try:
                parsed_json = json.loads(json_string)

                if 'wu_key' in parsed_json:
                    WU_KEY = parsed_json['wu_key']
                if 'wu_city' in parsed_json:
                    WU_CITY = parsed_json['wu_city']
                if 'wu_state' in parsed_json:
                    WU_STATE = parsed_json['wu_state']
            except ValueError, e:
                logger.warning('Invalid Weather Underground JSON configuration in %s: %s' % (wu_file, e))
                pass
        finally:
            f.close()
    except IOError, e:
        logger.warning('Could not open/read Weather Undeground configuration in %s: %s' % (wu_file, e))

    if WU_CITY is None or WU_STATE is None or WU_KEY is None:
        logger.warning('Weather Underground unconfigured. Simulating.')
        return None
    else:
        return ''.join([WU_API_URL, WU_KEY, WU_API_QUERY, WU_STATE, '/', WU_CITY, '.json'])


def backoff_sleep(reset=False, delay=2, max_delay=1024):
    """
    Sleep function with exponential backoff with deterministic maximum and option to reset delay to default.

    :param reset: Resets the next run to default delay without backoff
    :param delay: Initial backoff delay
    :param max_delay: Maximal backoff after which delay becomes constant
    """
    global _backoff_delay

    logger = logging.getLogger(sys._getframe().f_code.co_name)

    if reset:
        _backoff_delay = None
    else:
        if not '_backoff_delay' in globals() or _backoff_delay is None:
            _backoff_delay = delay

        logger.info('Backoff initiated for the duration of %d seconds.' % _backoff_delay)
        time.sleep(_backoff_delay)

        _backoff_delay *= 2
        if _backoff_delay > max_delay:
            _backoff_delay = max_delay


def read_rpi_cpu():
    """
    Fetch temperature from CPU0 thermal zone from /proc file and return float.

    :return: CPU0 temperature in Celsius
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


def read_weather_underground(weather_underground_url=None):
    """
    Poll Weather Underground API for current outdoor temperature in Celsius.

    :param weather_underground_url: Full Weather Underground API url for current city, state and with proper API key
    :return: temperature in Celsius, real or fake temperature
    """
    logger = logging.getLogger(sys._getframe().f_code.co_name)

    if weather_underground_url is None:
        return WU_FAKE_TEMP

    try:
        f = urllib2.urlopen(weather_underground_url)

        try:
            json_string = f.read()
        finally:
            f.close()
    except urllib2.URLError, e:
        logger.error('Could not communicate with Weather Underground API: %s' % e)
        return WU_FAKE_TEMP

    try:
        parsed_json = json.loads(json_string)
    except ValueError, e:
        logger.warning('Invalid JSON from Weather Undeground API: %s' % e)
        return WU_FAKE_TEMP

    try:
        temp_c = parsed_json['current_observation']['temp_c']
    except KeyError, e:
        logger.warning('Invalid JSON from Weather Undeground API: %s' % e)
        return WU_FAKE_TEMP

    return temp_c


def login_gdocs():
    """
    Login to Google Docs, open Spreadsheet and open a specific worksheet matching the current year
    and month preferably.

    :return: Google Docs Spreadsheet active worksheet object
    """
    logger = logging.getLogger(sys._getframe().f_code.co_name)

    if GDOCS_EMAIL is None or GDOCS_PASSWORD is None or GDOCS_SHEET is None:
        return None

    try:
        g_conn = gspread.login(GDOCS_EMAIL, GDOCS_PASSWORD)
    except gspread.GSpreadException, e:
        logger.error('Problem with Google Docs authentication: %s' % e)
        return None
    except (socket.error, socket.gaierror, socket.timeout), e:
        logger.error('Problem contacting Google Docs: %s. Continuing without.' % e)
        return None

    try:
        gdc = g_conn.open(GDOCS_SHEET)
    except gspread.SpreadsheetNotFound, e:
        logger.error('No such spreadsheet on Google Docs account: %s. Continuing without.' % e)
        return None
    except (socket.error, socket.gaierror, socket.timeout), e:
        logger.error('Problem contacting Google Docs: %s. Continuing without.' % e)
        return None

    sheet_pattern = datetime.datetime.now().strftime(GDOCS_SHEET_PATTERN)
    try:
        gdc_worksheet = gdc.worksheet(sheet_pattern)
    except gspread.WorksheetNotFound, e:
        logger.info('No such worksheet on Google Docs account: %s. Will create.' % e)

        # XXX: hardcoded number of columns for now and hardcoded descriptions
        try:
            gdc_worksheet = gdc.add_worksheet(title=sheet_pattern, rows=1, cols=5)

            # date_stamp, cpu_temp, bmp_temp, dht_hum, bmp_pres, wu_temp)
            gdc_worksheet.append_row((
                'Date/Time', 'CPU Temperature [C]', 'BMP Temperature [C]', 'DHT Humidity [%]', 'BMP Pressure [hPa]',
                'WU Temperature [C]'))
            logger.debug('Successfully created Google Docs worksheet: %s' % sheet_pattern)
        except gspread.GSpreadException, e:
            logger.error('Unable to create new Google Docs worksheet: %e. Continuing without.' % e)
            return None
    except (gspread.GSpreadException, gspread.HTTPError), e:
        logger.error('Could not open worksheet on Google Docs account: %s' % e)
        return None
    except Exception, e:
        logger.error('Unable to open worksheet on Google Docs (unexpected situation): %s' % e)
        return None

    return gdc_worksheet


def write_gdocs(date_stamp, cpu_temp, bmp_temp, dht_hum, bmp_pres, wu_temp):
    """
    Write a row with sensor data to Google Docs Spreadsheet active worksheet.

    :param date_stamp: date stamp readout
    :param cpu_temp: CPU temperature readout
    :param bmp_temp: BMP temperature readout
    :param dht_hum: DHT humidity readout
    :param bmp_pres: BMP pressure readout
    :param wu_temp: Weather Underground temperature readout
    """
    logger = logging.getLogger(sys._getframe().f_code.co_name)

    gdc_worksheet = login_gdocs()

    if gdc_worksheet is not None:
        try:
            gdc_worksheet.append_row((date_stamp, cpu_temp, bmp_temp, dht_hum, bmp_pres, wu_temp))
            logger.debug('Successfully published data to Google Docs.')
        except (gspread.GSpreadException, gspread.HTTPError), e:
            logger.error('Unable to add new row to Google Docs worksheet: %s' % e)
        except AttributeError, e:
            logger.error('Unable to add new row (invalid data) to Google Docs worksheet: %s' % e)
        except Exception, e:
            logger.error('Unable to add new row (unexpected situation): %s' % e)


def publish_data(s_cpu, s_humidity, s_pressure, s_temp, s_wu):
    """
    Publish all gathered data to PlotLy and Google Docs Spreadsheet.

    :param s_cpu: Plotly stream for CPU temperature readout
    :param s_humidity: Plotly stream for DHT humidity readout
    :param s_pressure: Plotly stream for BMP pressure readout
    :param s_temp: Plotly stream for BMP temperature readout
    :param s_wu: Plotly strem for Weather Underground temperature readout
    """
    global DATA_QUEUE

    logger = logging.getLogger(sys._getframe().f_code.co_name)

    while True:
        try:
            s_cpu.open()
            s_temp.open()
            s_humidity.open()
            s_pressure.open()
            s_wu.open()
            logger.debug('Successfully opened stream to PlotLy.')
        except socket.error, e:
            logger.error('Socket error connecting to Plotly: %s. Retrying...' % e)
            backoff_sleep(delay=60)
            continue

        while True:
            try:
                date_stamp, cpu_temp, bmp_temp, dht_hum, bmp_pres, wu_temp = DATA_QUEUE.get(block=True)

                # write to Google Docs
                write_gdocs(date_stamp, cpu_temp, bmp_temp, dht_hum, bmp_pres, wu_temp)

                # push data to Plotly
                try:
                    s_cpu.write(dict(x=date_stamp, y=cpu_temp))
                    s_temp.write(dict(x=date_stamp, y=bmp_temp))
                    s_humidity.write(dict(x=date_stamp, y=dht_hum))
                    s_pressure.write(dict(x=date_stamp, y=bmp_pres))
                    s_wu.write(dict(x=date_stamp, y=wu_temp))

                    backoff_sleep(reset=True)
                    logger.debug('Successfully published data to PlotLy.')
                except (IOError, socket.error, plotly.exceptions.PlotlyError), e:
                    logger.error('Socket error writing to Plotly: %s. Retrying...' % e)
                    DATA_QUEUE.put((date_stamp, cpu_temp, bmp_temp, dht_hum, bmp_pres, wu_temp))
                    backoff_sleep(delay=60)
                    break
            finally:
                try:
                    s_cpu.close()
                    s_temp.close()
                    s_humidity.close()
                    s_pressure.close()
                    s_wu.close()
                except plotly.exceptions.PlotlyError:
                    pass


def gather_data():
    """
    Gather all data from DHT and BMP sensors and graph on Plotly. Tries to be resilient to most intermittent
    errors.
    """
    logger = logging.getLogger(sys._getframe().f_code.co_name)

    init_led()
    bmp = init_bmp()
    wu_url = init_weather_underground()
    s_cpu, s_humidity, s_pressure, s_temp, s_wu = init_plotly()
    init_gdocs()

    t = threading.Thread(target=publish_data, args=(s_cpu, s_humidity, s_pressure, s_temp, s_wu))
    t.daemon = True
    t.start()

    while True:
        # pull CPU0 temperature
        try:
            cpu_temp = read_rpi_cpu()
        except RuntimeError, e:
            logger.error('CPU0 thermal zone reading failure: %s' % e)
            sys.exit(1)

        # pull DHT temperature and humidity
        try:
            dht_hum, dht_temp = Adafruit_DHT.read_retry(DHT_VER, DHT_GPIO)
        except RuntimeError, e:
            logger.error('GPIO DHT reading failure: %s' % e)
            sys.exit(1)

        # pull BMP temperature and pressure
        try:
            bmp_temp = bmp.readTemperature()
            bmp_pres = bmp.readPressure() / 100.0
        except IOError, e:
            logger.error('I2C BMP085 reading failure: %s' % e)
            sys.exit(1)

        # pull Weather Underground outdoor temperature
        wu_temp = read_weather_underground(weather_underground_url=wu_url)

        date_stamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')

        # gather all outputs into a single string
        gathered_out = 'CPU Temperature: %.2f ºC | ' \
                       'DHT Humidity: %.2f %% | ' \
                       'DHT Temperature: %.2f ºC | ' \
                       'BMP Temperature: %.2f ºC | ' \
                       'BMP Pressure: %.2f hPa | ' \
                       'WU Temperature: %.2f ºC' % (cpu_temp, dht_hum, dht_temp, bmp_temp, bmp_pres, wu_temp)
        logger.debug(gathered_out)

        DATA_QUEUE.put((date_stamp, cpu_temp, bmp_temp, dht_hum, bmp_pres, wu_temp))

        time.sleep(SLEEP_DELAY)


def run():
    """
    Generic main() block.
    """
    logger = logging.getLogger(sys._getframe().f_code.co_name)

    my_daemon = True
    my_debug = False

    if 'nodaemon' in sys.argv:
        my_daemon = False
    if 'debug' in sys.argv:
        my_debug = True
        my_daemon = False

    init_logging(my_debug)

    if os.geteuid() != 0:
        logger.error('You need root to be able to read GPIO, I2C and CPU thermal zones.')
        sys.exit(1)

    # setup signal handler
    signal.signal(signal.SIGINT, signal_handler)

    # preferably daemonize
    if my_daemon:
        with daemon.DaemonContext():
            gather_data()
    else:
        gather_data()


if __name__ == '__main__':
    run()
