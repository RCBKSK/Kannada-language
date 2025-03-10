from http.server import HTTPServer, BaseHTTPRequestHandler
import os
import sys
import threading
import time
import json
import datetime

# Health status tracking
health_info = {
    "status": "starting",
    "start_time": datetime.datetime.now().isoformat(),
    "last_activity": datetime.datetime.now().isoformat(),
    "requests_count": 0,
    "process_info": {
        "pid": os.getpid(),
        "python_version": sys.version,
        "platform": sys.platform
    }
}

def update_health(status=None):
    """Update health information"""
    health_info["last_activity"] = datetime.datetime.now().isoformat()
    health_info["requests_count"] += 1
    if status:
        health_info["status"] = status

class EnhancedHTTPHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        """Override to provide more visible logging"""
        print(f"[HTTP Server] {self.address_string()} - {format % args}")

    def do_GET(self):
        update_health()

        if self.path == "/health":
            # Return detailed health information
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(health_info, indent=2).encode('utf-8'))
        else:
            # Default response
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'LokBot is running\n')
            self.wfile.write(f"Server time: {datetime.datetime.now().isoformat()}\n".encode('utf-8'))
            self.wfile.write(f"Process uptime: {(datetime.datetime.now() - datetime.datetime.fromisoformat(health_info['start_time'])).total_seconds()} seconds\n".encode('utf-8'))

def run_heartbeat():
    """Periodic heartbeat to keep the server responsive"""
    while True:
        update_health("running")
        time.sleep(60)  # Update every minute

def run_server(port=3000):
    # Start heartbeat thread
    heartbeat_thread = threading.Thread(target=run_heartbeat, daemon=True)
    heartbeat_thread.start()

    # Start HTTP server
    server_address = ('0.0.0.0', port)
    httpd = HTTPServer(server_address, EnhancedHTTPHandler)
    print(f"Enhanced HTTP server started on port {port}")
    update_health("running")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        update_health("shutdown")
        print("Server shutting down")
        httpd.server_close()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 3000))
    run_server(port)