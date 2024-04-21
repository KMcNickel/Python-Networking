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
        self._sock: Optional[socket.socket] = None
        self._canSend: bool = canSend
        self._canReceive: bool = canReceive
        self._canAccept: bool = canAccept
        self._connected_handler: list[Callable[[networkSocket], None]] = []
        self._disconnected_handler: list[Callable[[networkSocket], None]] = []
        self._receive_handler: list[Callable[[networkSocket, str], None]] = []
        self._clients: list[remoteClientSocket] = []
        self._instanceName = instanceName
        self._logger: logging.Logger = logging.getLogger(instanceName)
        self._encoding: str = encoding

        self.isConnected: bool = False

    def create_socket(self, type: socket.SocketKind):
        if self._sock is None:
            raise InvalidOperationException("The socket already exists and must be closed before creating a new one")
        # The only family we support currently is AF_INET (IPv4)
        self._logger.debug("Creating socket")
        self._sock = socket.socket(socket.AF_INET, type)

    def send_data_raw(self, data: bytes):
        if self._sock is None:
            raise InvalidOperationException("This socket is not open")
        if not self._canSend:
            raise InvalidOperationException("This socket does not support sending data")
        self._logger.debug(f"Sending {data.count} bytes: {data}")
        self._sock.sendall(data)

    def send_data(self, data: str):
        dataBytes = data.encode(self._encoding)  #TODO: Error handling
        self.send_data_raw(dataBytes)

    def get_client_count(self):
        return len(self._clients)
    
    def is_this_socket(self, sock: socket.socket):
        if self._sock is None:
            return False
        
    def is_client_of_this_socket(self, sock: socket.socket):
        for clientSock in self._clients:
            if sock == clientSock._sock:
                return True
        return False
    
    def register_to_selector(self, selector: selectors.DefaultSelector):
        if self._sock is None:
            raise InvalidOperationException("Socket cannot be registered as it does not exist")
        selector.register(self._sock, selectors.EVENT_READ)

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

    def close(self, selector: Optional[selectors.DefaultSelector]):
        self._logger.debug("Closing socket")
        if self._sock is not None:
            if selector is not None:
                selector.unregister(self._sock) # TODO: Error handling
            self._sock.close()
            self._sock = None

class remoteClientSocket(networkSocket):
    def __init__(self, remoteAddress: Optional[tuple[str, int]], instanceName: str, sock: socket.socket):
        self.remoteAddress = sock.getpeername() if remoteAddress is None else remoteAddress
        super().__init__(True, True, False, instanceName)
        self._sock = sock

class tcpServerSocket(networkSocket):
    def __init__(self, boundAddress: tuple[str, int], instanceName: str):
        self.boundAddress = boundAddress
        super().__init__(True, True, True, instanceName)

    def open(self):
        if self._sock is None:
            raise InvalidOperationException("This socket is not open")
        self._logger.debug("Opening socket")
        super().create_socket(socket.SOCK_STREAM)
        self._sock.bind(self.boundAddress)   #TODO: Error Handling
        self._sock.listen()

    def accept_connection(self):
        if self._sock is None:
            raise InvalidOperationException("This socket is not open")
        conn, addr = self._sock.accept()
        self._logger.debug(f"Received connection from {addr}")
        self._clients.append(remoteClientSocket(addr, self._instanceName, conn))

class tcpClientSocket(networkSocket):
    def __init__(self, remoteAddress: tuple[str, int], boundAddress: Optional[tuple[str, int]], instanceName: str):
        self.boundAddress = boundAddress
        self.remoteAddress = remoteAddress
        super().__init__(True, True, False, instanceName)

    def open(self):
        if self._sock is None:
            raise InvalidOperationException("This socket is not open")
        self._logger.debug("Opening socket")
        super().create_socket(socket.SOCK_STREAM)
        if self.boundAddress is not None:
            self._sock.bind(self.boundAddress)   #TODO: Error Handling
        try:
            self._sock.connect(self.remoteAddress)
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
        if self._sock is None:
            raise InvalidOperationException("This socket is not open")
        self._logger.debug("Opening socket")
        super().create_socket(socket.SOCK_DGRAM)
        if self.boundAddress is not None:
            self._sock.bind(self.boundAddress)   #TODO: Error Handling
            self._sock.listen()

class networkManager:
    def __init__(self, instanceName: Optional[str]):
        loggerName = "networkManager" if instanceName is None else f"networkManager.{instanceName}"
        self._logger = logging.getLogger(loggerName)
        self._selector = selectors.DefaultSelector()
        self._sockets: list[networkSocket] = []

    def create_socket(self, sockInfo: networkSocket):
        self._sockets.append(sockInfo)
        sockInfo.register_to_selector(self._selector)

    def close_socket(self, sockInfo: networkSocket):
        sockInfo.close(self._selector)

    def _find_sock_info(self, sock: socket.socket):
        for sockInfo in self._sockets:
            if sockInfo.is_this_socket(sock) or sockInfo.is_client_of_this_socket(sock):
                return sockInfo
        return None

    def run_once(self):
        events = self._selector.select()    # TODO: Error Handling
        for key, mask in events:
            sock: socket.socket = key.fileobj #type: ignore
            sockInfo = self._find_sock_info(sock)
            if sockInfo is None:
                self._logger.warn(f"Unable to locate a socket to associate with event. Remote: {key.fileobj}")
            else:
                pass # TODO: Keep going

    def run_forever(self):
        while True:
            self.run_once()

    def shutdown(self):
        for socket in self._sockets:
            socket.close(self._selector)