#!/usr/bin/env python

import fcntl
import optparse
import os.path
import random
import socket
import struct
import sys
import time
import webbrowser
from functools import partial
from threading import Thread

try:
    import tornado.web, tornado.ioloop, tornado.httpserver
except ImportError:
    print >>sys.stderr, "Requires Tornado webserver"
    sys.exit(1)

try:
    import cjson
    json_encode = cjson.encode
except ImportError:
    import json
    json_encode = json.dumps


STATIC_PATH = os.path.join(os.path.dirname(__file__), 'static')


def get_ip_address(ifname):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    return socket.inet_ntoa(fcntl.ioctl(
        s.fileno(),
        0x8915,  # SIOCGIFADDR
        struct.pack('256s', ifname[:15])
    )[20:24])


tpl_index = """<html>
<head>
<script src="/static/jquery-1.3.2.min.js"></script>
<script src="/static/flot/jquery.flot.min.js"></script>
</head>
<body>
<div style="text-align: center;"><h1>%(title)s</h1></div>
<div style="padding: 100px;">
    <div id="chartdiv" style="height:300px;width:100%%;"></div>
</div>
<script type="text/javascript">
var updates = 0;
var chartOpts = %(chart_opts)s;
var seriesPrep = (%(series_prep)s);
$.plot($("#chartdiv"), [], chartOpts);

(function() {
    $.getJSON('/update', function(data) {
        $.plot($("#chartdiv"), [seriesPrep(data)], chartOpts);
        if (++updates == 10)
            window.location.href=window.location.href;
    });
    window.setTimeout(arguments.callee, 1000);
})();
</script>
</div>
</body>
</html>"""


class IndexHandler(tornado.web.RequestHandler):
    def get(self):
        options = self.application.options
        
        chart_min = None
        if options.interval:
            chart_min = options.length * options.interval * -1
        
        chart_max = 0
        if not options.realtime:
            chart_max = None
        
        chart_opts = self.application.series.get_chart_opts()
        
        out = tpl_index % {
            'title': (self.application.options.title or ''),
            'chart_min': json_encode(chart_min),
            'chart_max': json_encode(chart_max),
            'chart_opts': json_encode(chart_opts),
            'series_prep': chart_opts['series_prep'],
        }
        self.write(out)


class UpdateHandler(tornado.web.RequestHandler):
    def get(self):
        self.set_header("Content-type", "application/json")
        self.write(json_encode(list(self.application.series)))


class Application(tornado.web.Application):
    def __init__(self, options, series, *args, **kwargs):
        self.ioloop = tornado.ioloop.IOLoop.instance()
        self.options = options
        self.series = series
        
        super(Application, self).__init__(*args, **kwargs)

        Thread(target=self._read_input).start()
    
    def _read_input(self):
        while True:
            data = sys.stdin.readline()
            if data == '':
                break
            cb = partial(self.series.append, data.strip())
            self.ioloop.add_callback(cb)


BASE_CHART_OPTS = {
    'series': {
        'points': {
            'show': False,
        },
        'lines': {
            'fill': True,
            'fillColor': "rgba(100, 100, 100, .5)",
            'lineWidth': 0
        }
    },
    'xaxis': {},
    'series_prep': 'function(s) { return s; }',
}



class Series(list):
    def __init__(self, options, ioloop, *args):
        self.options = options
        self.ioloop = ioloop
        super(Series, self).__init__(*args)

    def get_chart_opts(self):
        return BASE_CHART_OPTS
    
    def __repr__(self):
        return "<%s>" % self.__class__.__name__


class LiteralSeries(Series):
    def append(self, data):
        try:
            val = float(data)
        except:
            val = None
        super(LiteralSeries, self).append(val)

        if len(self) > self.options.length:
            self.pop(0)
    
    def __iter__(self):
        return enumerate(Series.__iter__(self))

class BaseRealtimeSeries(Series):
    def get_chart_opts(self):
        BASE_CHART_OPTS['xaxis']['mode'] = 'time'
        BASE_CHART_OPTS['series_prep'] =\
        """ function(s) {
                var ns = [];
                for (var i=0; i<s.length; i++) {
                    ns.push([s[i][0]*1000, s[i][1]]);
                }
            return ns;
        }"""
        return BASE_CHART_OPTS

class RealtimeIntervalSeries(BaseRealtimeSeries):
    def __init__(self, options, ioloop):
        super(IntervalSeries, self).__init__(options, ioloop)
        self._update()
    
    def append(self, data):
        try:
            val = float(data)
        except:
            val = 1
        self[-1][1] += val
    
    def _update(self):
        super(RealtimeIntervalSeries, self).append([time.time(), 0])
        
        if len(self) > self.options.length:
            self.pop(0)
        
        timeout = time.time() + self.options.interval
        self.ioloop.add_timeout(timeout, self._update)
        

class RealtimeLiteralSeries(BaseRealtimeSeries):
    def append(self, data):
        try:
            val = float(data)
        except:
            val = None
        super(RealtimeLiteralSeries, self).append([time.time(), val])

        if len(self) > self.options.length:
            self.pop(0)


def get_args():
    parser = optparse.OptionParser()
    parser.add_option('-t', '--title', dest='title', default=None)
    parser.add_option('-i', '--interval', dest='interval', type="float",
                      default=None)
    parser.add_option('-l', '--length', dest='length', type="int", default=300)
    parser.add_option('-p', '--port', dest='port', type="int",
                      default=random.randint(30000, 50000))
    parser.add_option('-r', '--realtime', action='store_true')
    return parser.parse_args()


def get_series_class(options):
    if options.realtime:
        if options.interval:
            return RealtimeIntervalSeries
        return RealtimeLiteralSeries
    return LiteralSeries


def main():
    options, args = get_args()
    
    ioloop = tornado.ioloop.IOLoop.instance()
    
    series = get_series_class(options)(options, ioloop)
    
    application = Application(options, series, [
        ('/', IndexHandler),
        ('/update', UpdateHandler),
    ], static_path=STATIC_PATH)
    
    try:
        ip = get_ip_address('eth0')
    except IOError:
        ip = '127.0.0.1'

    http_server = tornado.httpserver.HTTPServer(application, io_loop=ioloop)
    http_server.listen(options.port, ip)
    
    url = 'http://%s:%s/' % (ip, options.port)
    
    def announce():
        print >>sys.stderr, "wplot running at: " + url
    
    ioloop.add_callback(lambda: webbrowser.open_new_tab(url))
    ioloop.add_callback(announce)
    
    try:
        ioloop.start()
    except (KeyboardInterrupt, IOError) as e:
        pass


if __name__ == '__main__':
    main()
