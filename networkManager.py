import socket
import selectors
import logging
from typing import Callable, Optional
import networkSocket

class networkManager:
    def __init__(self, instanceName: Optional[str]):
        loggerName = "networkManager" if instanceName is None else f"networkManager.{instanceName}"
        self._logger = logging.getLogger(loggerName)
        self._selector = selectors.DefaultSelector()
        self._sockets: list[networkSocket.networkSocket] = []

    def create_socket(self, sockInfo: networkSocket):
        self._sockets.append(sockInfo)
        sockInfo.createSocket()
        self._selector.register(sockInfo, selectors.EVENT_READ)

    def _find_sock_info(self, sock: socket.socket):
        for sockInfo in self._sockets:
            if sockInfo._sock == sock:
                return sockInfo
            for clientInfo in sockInfo._clients:
                if clientInfo._sock == sock:
                    return sockInfo
        return None

    def runOnce(self):
        events = self._selector.select()    # TODO: Error Handling
        for key, mask in events:
            sockInfo = self._find_sock_info(key.fileobj)
            if sockInfo is None:
                self._logger.warn(f"Unable to locate a socket to associate with event. Remote: {key.fileobj}")
            else:
                pass # TODO: Keep going

    def runForever(self):
        while True:
            self.runOnce()

    def shutdown(self):
        for socket in self._sockets:
            socket.close()