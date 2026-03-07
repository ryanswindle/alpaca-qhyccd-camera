import os
import socket
from threading import Thread

from log import get_logger


logger = get_logger()


class DiscoveryResponder(Thread):
    """Alpaca device discovery responder."""
    
    def __init__(self, host: str, port: int):
        Thread.__init__(self, name="Discovery", daemon=True)
        self.response = f'{{"AlpacaPort": {port}}}'
        
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if os.name != "nt":
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)

        try:
            self.sock.bind((host, 32227))
        except Exception as e:
            self.sock.close()
            logger.warning(f"Failure to bind discovery responder: {e}")
            raise

        logger.info(f"Discovery responder listening on port 32227")
        self.start()
    
    def run(self):
        while True:
            data, addr = self.sock.recvfrom(1024)
            if b'alpacadiscovery1' in data.lower():
                logger.info(f"Discovery request from {addr}")
                self.sock.sendto(self.response.encode(), addr)