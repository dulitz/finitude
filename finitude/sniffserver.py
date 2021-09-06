"""
sniffserver.py

The sniffserver dumps all the sniffed data. Useful paths:
   /anything.json -- get the data dump
   /stop -- stop data collection
   /start -- restart data collection
   /read -- send a READ frame
   /write -- send a WRITE frame

e.g.
curl --data-urlencode system=lowerlevel --data-urlencode register=0104 --data-urlencode dest=8001 --data-urlencode source=3001 http://10.188.2.175:8001/read
"""

import json, logging, threading

from cgi import FieldStorage
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server, WSGIServer

from . import frames

LOGGER = logging.getLogger('finitude')


class _ThreadingWSGISniffServer(ThreadingMixIn, WSGIServer):
    """Thread per request HTTP server."""
    # Make worker threads "fire and forget". Beginning with Python 3.7 this
    # prevents a memory leak because ``ThreadingMixIn`` starts to gather all
    # non-daemon threads in a list in order to join on them at server close.
    daemon_threads = True


def convert_word_to_bytes(word):
    if len(word) != 4:
        raise frames.CarrierError(f'{word} is invalid')
    assert int(word, 16)  # raises ValueError if not valid hex
    return bytes([int(word[0:2], 16), int(word[2:], 16)])


def start_sniffserver(port, monitors):
    def app(environ, start_response):
        # Prepare parameters
        method = environ.get('REQUEST_METHOD')
        accept_header = environ.get('HTTP_ACCEPT')
        path = environ['PATH_INFO']
        params = parse_qs(environ.get('QUERY_STRING', ''))
        if path == '/favicon.ico':
            # Serve empty response for browsers
            status = '200 OK'
            header = ('', '')
            output = b''
        elif path.endswith('.json'):
            js = {}
            for m in monitors:
                index_frame = sorted([(i, f) for (f, i) in m.framedata_to_index.items()])
                assert index_frame[0][0] == 1, index_frame[0]
                lastindex_by_name = {}
                outframes = []
                for (t, name, index) in m.frames:
                    if index-1 >= len(index_frame):
                        break  # another frame came in while we were running
                    last = lastindex_by_name.get(name)
                    if last is None:
                        outframes.append((t, name, index, None))
                    else:
                        lastdata = index_frame[last-1][1]
                        thisdata = index_frame[index-1][1]
                        if len(lastdata) != len(thisdata):
                            changes = f'len {len(lastdata)}->{len(thisdata)}'
                        else:
                            changes = []
                            for (last, this, i) in zip(lastdata, thisdata, range(len(lastdata))):
                                if last != this:
                                    changes.append((i, last, this))
                            if len(changes) > 8:
                                changes = len(changes)
                            outframes.append((t, name, index, changes))
                    lastindex_by_name[name] = index
                js[m.name] = {
                    'frames_by_index': [None] + [frames.bytestohex(f) for (i, f) in index_frame],
                    'sequence': outframes,
                    'frames_by_register': [(name, str(rf[1])) for (name, rf) in m.register_to_rest.items()],
                }
            status = '200 OK'
            header = ('Content-type', 'application/json')
            output = json.dumps(js).encode()
        elif path.startswith('/start'):
            LOGGER.info('data collection started')
            for m in monitors:
                m.set_store_frames(True)
            status = '200 OK'
            header = ('', '')
            output = b'data collection started'
        elif path.startswith('/stop'):
            LOGGER.info('data collection stopped')
            for m in monitors:
                m.set_store_frames(False)
            status = '200 OK'
            header = ('', '')
            output = b'data collection stopped'
        elif (path == '/write' or path == '/read') and method == 'POST':
            func = frames.Function.WRITE if path == '/write' else frames.Function.READ
            post_env = environ.copy()
            post_env['QUERY_STRING'] = ''
            fs = FieldStorage(
                fp=environ['wsgi.input'], environ=post_env, keep_blank_values=True
            )
            system = fs['system'].value
            register = bytes([0]) + convert_word_to_bytes(fs['register'].value)
            mask = (bytes([0]) + convert_word_to_bytes(fs['mask'].value)) if 'mask' in fs else b''
            hex = fs['data'].value if 'data' in fs else b''
            data = bytes([int(hi + lo, 16) for (hi, lo) in zip(*([iter(hex)]*2))])
            frame = frames.AssembledFrame(convert_word_to_bytes(fs['dest'].value),
                                          convert_word_to_bytes(fs['source'].value),
                                          func,
                                          register + mask + data)
            for m in monitors:
                if system == m.name:
                    for i in range(4): # try 4 times to write
                        LOGGER.info(f'{system} writing {frame}')
                        resp = m.send_with_response(frame, timeout=2.0)
                        if resp:
                            LOGGER.info(f'{system} response: {resp}')
                            break
                    else:
                        LOGGER.info(f'{system} no response')
                    r = f'"{resp}"' if resp else 'null'
                    output = '{\n  "request": ' + f'"{frame}",\n  "response": {r}\n' + '}\n'
                    status = '200 OK'
                    header = ('Content-type', 'application/json')
                    break
            else:
                status = '408 Client Error'
                header = ('', '')
                output = f'system {system} not found'
            output = output.encode()
        start_response(status, [header])
        return [output]

    LOGGER.info(f'serving sniffed data on {port}')
    httpd = make_server('', port, app, _ThreadingWSGISniffServer)
    t = threading.Thread(target=httpd.serve_forever)
    t.start()
