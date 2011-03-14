import fcntl
import optparse
import os.path
import random
import socket
import struct
import sys
import time
import webbrowser

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
var chartOpts = {
    series: {
        points: {
            show: false,
        },
        lines: {
            fill: true,
            fillColor: "rgba(100, 100, 100, .5)",
            lineWidth: 0
        }
    },
    xaxis: {
        max: 0,
        min: %(chart_min)s,
    },
};
$.plot($("#chartdiv"), [], chartOpts);

(function() {
    $.getJSON('/update', function(data) {
        $.plot($("#chartdiv"), [data], chartOpts);
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
        
        out = tpl_index % {
            'title': (self.application.options.title or ''),
            'chart_min': json_encode(chart_min),
        }
        self.write(out)


class UpdateHandler(tornado.web.RequestHandler):
    def get(self):
        self.set_header("Content-type", "application/json")
        
        now = time.time()
        values = [(t-now, i) for t, i in self.application.series]
        
        self.write(json_encode(values))


class Application(tornado.web.Application):
    def __init__(self, options, *args, **kwargs):
        self.ioloop = tornado.ioloop.IOLoop.instance()
        self.options = options
        self.series = self._get_series()
        
        self.ioloop.add_handler(sys.stdin.fileno(), self._handle_input,
                                self.ioloop.READ | self.ioloop.ERROR)
        
        super(Application, self).__init__(*args, **kwargs)
    
    def _get_series(self):
        if self.options.interval:
            cls = IntervalSeries
        else:
            cls = LiteralSeries
        return cls(self)
    
    def _handle_input(self, fileno, events):
        if events & self.ioloop.ERROR:
            self.ioloop.stop()
        else:
            data = sys.stdin.readline().strip()
            self.series.append(data)


class Series(list):
    def __init__(self, application, *args):
        self.application = application
        super(Series, self).__init__(*args)


class IntervalSeries(Series):
    def __init__(self, application):
        
        interval = application.options.interval
        length = application.options.length
        now = time.time()
        
        super(IntervalSeries, self).__init__(application)

        self._update()
    
    def append(self, data):
        try:
            val = float(data)
        except:
            val = 1
        self[-1][1] += val
    
    def _update(self):
        super(IntervalSeries, self).append([time.time(), 0])
        
        if len(self) > self.application.options.length:
            self.pop(0)
        
        timeout = time.time() + self.application.options.interval
        self.application.ioloop.add_timeout(timeout, self._update)
        

class LiteralSeries(Series):
    def append(self, data):
        try:
            val = float(data)
        except:
            val = None
        super(LiteralSeries, self).append([time.time(), val])

        if len(self) > self.application.options.length:
            self.pop(0)


def get_args():
    parser = optparse.OptionParser()
    parser.add_option('-t', '--title', dest='title', default=None)
    parser.add_option('-i', '--interval', dest='interval', type="float",
                      default=None)
    parser.add_option('-l', '--length', dest='length', type="int", default=300)
    parser.add_option('-p', '--port', dest='port', type="int",
                      default=random.randint(30000, 50000))
    return parser.parse_args()


def main():
    options, args = get_args()
    
    application = Application(options, [
        ('/', IndexHandler),
        ('/update', UpdateHandler),
    ], static_path=STATIC_PATH)
    
    try:
        ip = get_ip_address('eth0')
    except IOError:
        ip = '127.0.0.1'

    http_server = tornado.httpserver.HTTPServer(application)
    http_server.listen(options.port)
    
    url = 'http://%s:%s/' % (ip, options.port)
    
    def announce():
        print >>sys.stderr, "wplot running at: " + url
    
    application.ioloop.add_callback(lambda: webbrowser.open_new_tab(url))
    application.ioloop.add_callback(announce)
    
    try:
        application.ioloop.start()
    except (KeyboardInterrupt, IOError) as e:
        pass


if __name__ == '__main__':
    main()
