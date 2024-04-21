import socket
import selectors
import logging
from typing import Callable, Optional

class InvalidOperationException(Exception):
    pass

class networkSocket:
    def __init__(self, canSend: bool, canReceive: bool, canAccept: bool, instanceName: str, encoding: str = "utf-8"):
        """
        Create a networkSocket object.

        Args:
            canSend: bool - True if the socket is capable of sending to a remote device (assuming the remote is alive and connected, if needed)
            canReceive: bool - True if the socket is capable of receiving from a remote device (assuming the remote is alive and connected, if needed)
            canAccept: bool - True if the socket is capable of accepting remote connections (ex: TCP servers)
            instanceName: str - The name of the logging instance
            encoding: str - The codec to use when converting between strings and bytes objects (utf-8 by default)
        """
        self.sock: Optional[socket.socket] = None
        self._canSend: bool = canSend
        self._canReceive: bool = canReceive
        self._canAccept: bool = canAccept
        self.isConnected: bool = False
        self._connected_handler: list[Callable[[networkSocket], None]] = []
        self._disconnected_handler: list[Callable[[networkSocket], None]] = []
        self._receive_handler: list[Callable[[networkSocket, str], None]] = []
        self.clients: list[remoteClientSocket] = []
        self._instanceName = instanceName
        self._logger: logging.Logger = logging.getLogger(instanceName)
        self._encoding: str = encoding

    def createSocket(self, type: socket.SocketKind):
        if self.sock is None:
            raise InvalidOperationException("The socket already exists and must be closed before creating a new one")
        # The only family we support currently is AF_INET (IPv4)
        self._logger.debug("Creating socket")
        self.sock = socket.socket(socket.AF_INET, type)

    def send_data_raw(self, data: bytes):
        if self.sock is None:
            raise InvalidOperationException("This socket is not open")
        if not self._canSend:
            raise InvalidOperationException("This socket does not support sending data")
        self._logger.debug(f"Sending {data.count} bytes: {data}")
        self.sock.sendall(data)

    def send_data(self, data: str):
        dataBytes = data.encode(self._encoding)  #TODO: Error handling
        self.send_data_raw(dataBytes)

    def _handle_connect(self):
        self._logger.debug("Socket connected")
        for handler in self._connected_handler:
            handler(self)

    def _handle_disconnect(self):
        self._logger.debug("Socket disconnected")
        for handler in self._disconnected_handler:
            handler(self)

    def _handle_receive(self, data: bytes):
        self._logger.debug("Socket received data")
        dataString = data.decode(self._encoding)  #TODO: Error handling
        self._logger.debug(f"Data: {dataString}")
        for handler in self._receive_handler:
            handler(self, dataString)

    def close(self):
        self._logger.debug("Closing socket")
        if self.sock is not None:
            self.sock.close()
            self.sock = None

class remoteClientSocket(networkSocket):
    def __init__(self, remoteAddress: Optional[tuple[str, int]], instanceName: str, sock: socket.socket):
        self.remoteAddress = sock.getpeername() if remoteAddress is None else remoteAddress
        super().__init__(True, True, False, instanceName)
        self.sock = sock

class tcpServerSocket(networkSocket):
    def __init__(self, boundAddress: tuple[str, int], instanceName: str):
        self.boundAddress = boundAddress
        super().__init__(True, True, True, instanceName)

    def open(self):
        if self.sock is None:
            raise InvalidOperationException("This socket is not open")
        self._logger.debug("Opening socket")
        super().createSocket(socket.SOCK_STREAM)
        self.sock.bind(self.boundAddress)   #TODO: Error Handling
        self.sock.listen()

    def accept_connection(self):
        if self.sock is None:
            raise InvalidOperationException("This socket is not open")
        conn, addr = self.sock.accept()
        self._logger.debug(f"Received connection from {addr}")
        self.clients.append(remoteClientSocket(addr, self._instanceName, conn))

class tcpClientSocket(networkSocket):
    def __init__(self, remoteAddress: tuple[str, int], boundAddress: Optional[tuple[str, int]], instanceName: str):
        self.boundAddress = boundAddress
        self.remoteAddress = remoteAddress
        super().__init__(True, True, False, instanceName)

    def open(self):
        if self.sock is None:
            raise InvalidOperationException("This socket is not open")
        self._logger.debug("Opening socket")
        super().createSocket(socket.SOCK_STREAM)
        if self.boundAddress is not None:
            self.sock.bind(self.boundAddress)   #TODO: Error Handling
        try:
            self.sock.connect(self.remoteAddress)
        except Exception as e:
            return e
        else:
            self._handle_connect()

class udpSocket(networkSocket):
    def __init__(self, remoteAddress: Optional[tuple[str, int]], boundAddress: Optional[tuple[str, int]], instanceName: str):
        if remoteAddress is None and boundAddress is None:
            raise ValueError("The local or remote address must be specified")
        self.boundAddress = boundAddress
        self.remoteAddress = remoteAddress
        super().__init__(remoteAddress is not None, boundAddress is not None, False, instanceName)

    def open(self):
        if self.sock is None:
            raise InvalidOperationException("This socket is not open")
        self._logger.debug("Opening socket")
        super().createSocket(socket.SOCK_DGRAM)
        if self.boundAddress is not None:
            self.sock.bind(self.boundAddress)   #TODO: Error Handling
            self.sock.listen()

class networkManager:
    def __init__(self, instanceName: Optional[str]):
        loggerName = "networkManager" if instanceName is None else f"networkManager.{instanceName}"
        self._logger = logging.getLogger(loggerName)
        self._selector = selectors.DefaultSelector()
        self.sockets: list[networkSocket] = []

    def createsocket(self, sockInfo: networkSocket):
        if sockInfo.sock is None:
            raise InvalidOperationException("This socket is not open")
        self.sockets.append(sockInfo)
        self._selector.register(sockInfo.sock, selectors.EVENT_READ)

    def _findsock_info(self, sock: socket.socket):
        for sockInfo in self.sockets:
            if sockInfo.sock == sock:
                return sockInfo
            for clientInfo in sockInfo.clients:
                if clientInfo.sock == sock:
                    return sockInfo
        return None

    def runOnce(self):
        events = self._selector.select()    # TODO: Error Handling
        for key, mask in events:
            sock: socket.socket = key.fileobj #type: ignore
            sockInfo = self._findsock_info(sock)
            if sockInfo is None:
                self._logger.warn(f"Unable to locate a socket to associate with event. Remote: {key.fileobj}")
            else:
                pass # TODO: Keep going

    def runForever(self):
        while True:
            self.runOnce()

    def shutdown(self):
        for socket in self.sockets:
            socket.close()