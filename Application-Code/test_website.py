import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthy":
            status = 200
            response_text = "Website is healthy"
        elif self.path == "/error":
            status = 500
            response_text = "Server Error"
        elif self.path == "/slow":
            time.sleep(10)
            status = 200
            response_text = "Slow Response"
        else:
            status = 404
            response_text = "Page not found"

        responde_data = json.dumps({"result": response_text}).encode("utf-8")

        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(responde_data)))
            self.end_headers()
            self.wfile.write(responde_data)
        except (BrokenPipeError, ConnectionResetError):
            pass


if __name__ == "__main__":
    website_server = ThreadingHTTPServer(("0.0.0.0", 8001), RequestHandler)
    print("Test website running on port 8001", flush=True)
    website_server.serve_forever()
