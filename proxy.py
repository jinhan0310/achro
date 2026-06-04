"""
아임웹 API CORS 프록시 - index.html 아임웹 불러오기 기능용
실행: python proxy.py
포트: 7777
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request, urllib.error

IMWEB_BASE = 'https://api.imweb.me'

class ProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # 로그 출력 생략

    def _cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'access-token, content-type, *')

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path == '/ping':
            self.send_response(200)
            self._cors_headers()
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            return
        self._proxy('GET')

    def do_POST(self):
        self._proxy('POST')

    def _proxy(self, method):
        target = IMWEB_BASE + self.path
        headers = {}
        if self.headers.get('access-token'):
            headers['access-token'] = self.headers['access-token']
        if self.headers.get('content-type'):
            headers['content-type'] = self.headers['content-type']

        body = None
        if method == 'POST':
            length = int(self.headers.get('content-length', 0))
            body = self.rfile.read(length) if length else None

        try:
            req = urllib.request.Request(target, data=body, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self._cors_headers()
                self.end_headers()
                self.wfile.write(data)
        except Exception as e:
            self.send_response(502)
            self._cors_headers()
            self.end_headers()
            self.wfile.write(str(e).encode())

if __name__ == '__main__':
    server = HTTPServer(('localhost', 7777), ProxyHandler)
    print('아임웹 프록시 실행 중: http://localhost:7777')
    print('종료: Ctrl+C')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n프록시 종료')
