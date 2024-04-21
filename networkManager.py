import socket
import selectors
import logging
from typing import Callable, Optional, TypeVar

# TODO: GLOBAL - Ensure ALL selector calls have exception handling
# TODO: GLOBAL - Add socket info to ALL exceptions and log messages

class InvalidOperationException(Exception):
    pass

_A = TypeVar("_A")
_R = TypeVar("_R")

class EventHandlers(list[Callable[[_A], _R]]):
    def listen(self, handler: Callable[[_A], _R]):
        if not any(item == handler for item in self):
            self.append(handler)
            return True
        else:
            return False
        
    def unlisten(self, handler: Callable[[_A], _R]):
        self.remove(handler)

    def execute(self, arg: _A):
        for handler in self:
            handler(arg)

class networkSocket:
    def __init__(self, canSend: bool, canReceive: bool, canAccept: bool, instanceName: str, type: socket.SocketKind, encoding: str = "utf-8"):
        """
        Create a networkSocket object.

        Args:
            canSend: bool - True if the socket is capable of sending to a remote device (assuming the remote is alive and connected, if needed)
            canReceive: bool - True if the socket is capable of receiving from a remote device (assuming the remote is alive and connected, if needed)
            canAccept: bool - True if the socket is capable of accepting remote connections (ex: TCP servers)
            instanceName: str - The name of the logging instance
            type: socket.SocketKind - The type of socket to use. Generally socket.SOCK_STREAM for TCP and socket.SOCK_DGRAM for UDP
            encoding: str - The codec to use when converting between strings and bytes objects (utf-8 by default)
        """
        self._sock: Optional[socket.socket] = None
        self._clients: list[remoteClientSocket] = []
        self._instanceName = instanceName
        self._logger: logging.Logger = logging.getLogger(instanceName)
        self._encoding: str = encoding
        self._max_receive_length = 1024
        self._socket_type: socket.SocketKind = type

        self.canSend: bool = canSend
        self.canReceive: bool = canReceive
        self.canAccept: bool = canAccept
        self.connected_handler: EventHandlers[networkSocket, None]
        self.disconnected_handler: EventHandlers[networkSocket, None]
        self.receive_handler: EventHandlers[tuple[networkSocket, str], None]
        self.isConnected: bool = False

    def create_socket(self):
        if self._sock is None:
            raise InvalidOperationException("The socket already exists and must be closed before creating a new one")
        # The only family we support currently is AF_INET (IPv4)
        self._logger.debug("Creating socket")
        self._sock = socket.socket(socket.AF_INET, self._socket_type)

    def open(self):
        raise InvalidOperationException("Unable to open a socket from this class. A subclass must be used for proper implementation")

    def send_data_raw(self, data: bytes):
        if self._sock is None:
            raise InvalidOperationException("This socket is not open")
        if not self.canSend:
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
        if self._sock == sock:
            return True
        else:
            return False
        
    def is_client_of_this_socket(self, sock: socket.socket):
        for clientSock in self._clients:
            if sock == clientSock._sock:
                return True
        return False
    
    def register_to_selector(self, selector: selectors.BaseSelector):
        if self._sock is None:
            raise InvalidOperationException("Socket cannot be registered as it does not exist")
        selector.register(self._sock, selectors.EVENT_READ)

    def accept_connection(self, selector: selectors.BaseSelector):
        if not self.canAccept:
            raise InvalidOperationException("This socket cannot accept a connection")
        if self._sock is None:
            raise InvalidOperationException("This socket is not open")
        conn, addr = self._sock.accept()
        conn.setblocking(False)
        self._logger.info(f"Received connection from {addr}")
        remoteSocket = remoteClientSocket(self, addr, self._instanceName, conn)
        remoteSocket.register_to_selector(selector)
        selector.register(conn, selectors.EVENT_READ)
        self._clients.append(remoteSocket)

    def _handle_connect(self):
        self._logger.debug("Socket connected")
        self.connected_handler.execute(self)

    def _handle_disconnect(self):
        self._logger.debug("Socket disconnected")
        self.disconnected_handler.execute(self)

    def _handle_receive(self, data: bytes):
        self._logger.debug("Socket received data")
        dataString = data.decode(self._encoding)  #TODO: Error handling
        self._logger.debug(f"Data: {dataString}")
        self.receive_handler.execute((self, dataString))

    def close(self, selector: Optional[selectors.BaseSelector]):
        self._logger.debug("Closing socket")
        if self._sock is not None:
            if selector is not None:
                selector.unregister(self._sock) # TODO: Error handling
            self._sock.close()
            self._sock = None
        self._handle_disconnect()

    def process_data_event(self, key: selectors.SelectorKey, mask: int, isClient: bool, selector: selectors.BaseSelector):
        if self._sock is None:
            raise InvalidOperationException("Socket data cannot be processed as the socket does not exist. This should NEVER happen")
        if mask & selectors.EVENT_READ:
            try:
                received_data = self._sock.recv(self._max_receive_length)
            except Exception as e:   # TODO: Better Error Handling
                if isClient:
                    self._logger.warn(f"Exception occurred while trying to receive data from client. Connection will be closed. Exception: {str(e)}")
                    self.close(selector)
                else:
                    self._logger.warn(f"Exception occurred while trying to receive data on socket. Connection will be closed and reopened. Exception: {str(e)}")
                    self.close(selector)
                    self.create_socket()
                    self.open()
                return
            else:
                self._logger.debug(f"Received {len(received_data)} bytes")

                if received_data is not None:   #TODO: sort out this error
                    self._handle_receive(received_data)
                else:
                    if key.data:
                        self._logger.info(f"Closing connection to {key.data}")
                    else:
                        self._logger.warn("Closing connection to unknown host")
                    self.close(selector)


class remoteClientSocket(networkSocket):
    def __init__(self, localSocket: networkSocket, remoteAddress: Optional[tuple[str, int]], instanceName: str, sock: socket.socket):
        self.remoteAddress = sock.getpeername() if remoteAddress is None else remoteAddress
        super().__init__(True, True, False, instanceName, localSocket._socket_type)
        self._sock = sock
        self._parent_socket = localSocket

    def close(self, selector: Optional[selectors.BaseSelector]):
        super().close(selector)
        self._parent_socket._clients.remove(self)


class tcpServerSocket(networkSocket):
    def __init__(self, boundAddress: tuple[str, int], instanceName: str):
        self.boundAddress = boundAddress
        super().__init__(True, True, True, instanceName, socket.SOCK_STREAM)

    def open(self):
        if self._sock is None:
            raise InvalidOperationException("This socket is not open")
        self._logger.debug("Opening socket")
        super().create_socket()
        self._sock.bind(self.boundAddress)   #TODO: Error Handling
        self._sock.listen()
        self._handle_connect()

class tcpClientSocket(networkSocket):
    def __init__(self, remoteAddress: tuple[str, int], boundAddress: Optional[tuple[str, int]], instanceName: str):
        self.boundAddress = boundAddress
        self.remoteAddress = remoteAddress
        super().__init__(True, True, False, instanceName, socket.SOCK_STREAM)

    def open(self):
        if self._sock is None:
            raise InvalidOperationException("This socket is not open")
        self._logger.debug("Opening socket")
        super().create_socket()
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
        super().__init__(remoteAddress is not None, boundAddress is not None, False, instanceName, socket.SOCK_DGRAM)

    def open(self):
        if self._sock is None:
            raise InvalidOperationException("This socket is not open")
        self._logger.debug("Opening socket")
        super().create_socket()
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
            if sockInfo.is_this_socket(sock):
                return sockInfo, False
            if sockInfo.is_client_of_this_socket(sock):
                return sockInfo, True
        return None, None

    def run_once(self):
        events = self._selector.select()    # TODO: Error Handling
        for key, mask in events:
            sock: socket.socket = key.fileobj #type: ignore
            sockInfo, isClient = self._find_sock_info(sock)
            if sockInfo is None or isClient is None:
                self._logger.warn(f"Unable to locate a socket to associate with event. Remote: {key.fileobj}")
            else:
                if sockInfo.canAccept and key.data is None:
                    sockInfo.accept_connection(self._selector)
                else:
                    sockInfo.process_data_event(key, mask, isClient, self._selector)

    def run_forever(self):
        while True:
            self.run_once()

    def shutdown(self):
        for socket in self._sockets:
            socket.close(self._selector)