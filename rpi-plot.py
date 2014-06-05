#!/usr/bin/env python
# -*- coding: iso-8859-1 -*-

"""Raspberry PI temperature graphing PoC through PlotLy

   To be able to use this register a PlotLy account and invoke
   plotly.tools.set_credentials_file() like described in manual pages:
   https://plot.ly/python/getting-started/
"""

import time
import datetime

import plotly.plotly as py
import plotly.tools as tls
from plotly.graph_objs import Data, Layout, Figure, Stream, Scatter, YAxis, XAxis


USERNAME = tls.get_credentials_file()['username']
API_KEY = tls.get_credentials_file()['api_key']
STREAM_TOKEN = tls.get_credentials_file()['stream_ids'][0]
SLEEP_DELAY = 900

py.sign_in(USERNAME, API_KEY)

my_stream = Stream(token=STREAM_TOKEN, maxpoints=200)
my_data = Data([Scatter(x=[], y=[], stream=my_stream)])
my_layout = Layout(title='RPI Temperature', yaxis=YAxis(range=[-20, 100],
                                                        domain=[-20, 100], title='Temperature [C]'),
                   xaxis=XAxis(title='Time Series'))
my_fig = Figure(data=my_data, layout=my_layout)
unique_url = py.plot(my_fig, filename='my_rpi_stream',
                     auto_open=False, fileopt='overwrite')

s = py.Stream(STREAM_TOKEN)
s.open()

while True:
    try:
        sensor_data = float(open('/sys/class/thermal/thermal_zone0/temp',
                                 'r').read()) / 1000.
        date_stamp = datetime.datetime.now()
        data = dict(x=date_stamp.strftime('%Y-%m-%d %H:%M:%S.%f'),
                    y='%.2f' % sensor_data)
        s.write(data)
        time.sleep(SLEEP_DELAY)
    finally:
        s.close()
