from waitress import serve
from app import app
import socket

with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
    try:
        probe.connect(("192.0.2.1", 1))
        print("On your phone (same Wi-Fi), open: http://{}:5000".format(probe.getsockname()[0]))
    except OSError as error:
        print("Could not detect the Wi-Fi address: {}".format(error))
        print("Find the laptop's IPv4 address with ipconfig.")

print("Starting server on all network interfaces at port 5000")
serve(app, host="0.0.0.0", port=5000, threads=8)