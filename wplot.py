import webbrowser
import time
import sys
import optparse
import random
import socket
import fcntl
import struct

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


def get_ip_address(ifname):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    return socket.inet_ntoa(fcntl.ioctl(
        s.fileno(),
        0x8915,  # SIOCGIFADDR
        struct.pack('256s', ifname[:15])
    )[20:24])


tpl_index = """<html>
<head>
<script src="https://ajax.googleapis.com/ajax/libs/jquery/1.5.1/jquery.min.js"></script>
<script src="http://people.iola.dk/olau/flot/jquery.flot.js"></script>
</head>
<body>
<div style="text-align: center;"><h1>%(title)s</h1></div>
<div style="padding: 100px;">
    <div id="chartdiv" style="height:300px;width:100%%;"></div>
</div>
<script type="text/javascript">
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
    }
};
$.plot($("#chartdiv"), [], chartOpts);

(function() {
    $.getJSON('/update', function(data) {
        $.plot($("#chartdiv"), [data], chartOpts);
    });
    window.setTimeout(arguments.callee, 1000);
})();

window.setTimeout(function(){window.location.href=window.location.href}, 10000)
</script>
</div>
</body>
</html>"""


class IndexHandler(tornado.web.RequestHandler):
    def get(self):
        out = tpl_index % {
            'title': (self.application.options.title or ''),
        }
        self.write(out)


class UpdateHandler(tornado.web.RequestHandler):
    def get(self):
        self.set_header("Content-type", "application/json")
        
        now = time.time()
        values = [(t-now, i) for t, i in self.application.series]
        
        self.write(json_encode(values))


class Application(tornado.web.Application):
    def __init__(self, options, series, *args):
        self.io_loop = tornado.ioloop.IOLoop.instance()
        self.options = options
        self.series = series
        
        self.start_time = time.time()
        
        self.io_loop.add_handler(
            sys.stdin.fileno(), self._handle_input, self.io_loop.READ)
        
        super(Application, self).__init__(*args)
    
    def _handle_input(self, *args):
        data = sys.stdin.readline().strip()
        self.series.append(data)


class Series(list):
    def __init__(self, options, ioloop, *args):
        self.options = options
        self.ioloop = ioloop
        super(Series, self).__init__(*args)


class IntervalSeries(Series):
    def __init__(self, options, ioloop):

        now = time.time()
        series = []
        for i in range(options.length):
            series.append([now-(i*options.interval), None])
        
        super(IntervalSeries, self).__init__(options, ioloop, series)

        self.update()
    
    def append(self, data):
        try:
            val = float(data)
        except:
            val = 1
        self[-1][1] += val
    
    def update(self):
        super(IntervalSeries, self).append([time.time(), 0])
        
        if len(self) > self.options.length:
            self.pop(0)
        
        timeout = time.time() + self.options.interval
        self.ioloop.add_timeout(timeout, self.update)
        

class LiteralSeries(Series):
    def append(self, data):
        try:
            val = float(data)
        except:
            val = None
        super(LiteralSeries, self).append([time.time(), val])

        if len(self) > self.options.length:
            self.pop(0)



def main():
    parser = optparse.OptionParser()
    parser.add_option('-t', '--title', dest='title', default=None)
    parser.add_option('-i', '--interval', dest='interval', type="float",
                      default=None)
    parser.add_option('-l', '--length', dest='length', type="int", default=300)
    parser.add_option('-p', '--port', dest='port', type="int",
                      default=random.randint(30000, 50000))
    
    options, args = parser.parse_args()
    
    ioloop = tornado.ioloop.IOLoop.instance()

    if options.interval:
        series = IntervalSeries(options, ioloop)
    else:
        series = LiteralSeries(options, ioloop)
    
    application = Application(options, series, [
        ('/', IndexHandler),
        ('/update', UpdateHandler),
    ])
    http_server = tornado.httpserver.HTTPServer(application)
    http_server.listen(options.port)
    
    try:
        ip = get_ip_address('eth0')
    except:
        ip = '127.0.0.1'
    
    url = 'http://%s:%s/' % (ip, options.port)
    print "Running at: " + url
    
    application.io_loop.add_callback(
        lambda: webbrowser.open_new_tab(url))
    
    try:
        io_loop.start()
    except (KeyboardInterrupt, IOError):
        pass


if __name__ == '__main__':
    main()
