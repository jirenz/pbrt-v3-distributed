import zmq
import threading


def bytes2str(bytestring):
    if isinstance(bytestring, str):
        return bytestring
    else:
        return bytestring.decode('UTF-8')

def str2bytes(string):
    if isinstance(string, bytes):
        return string
    else:
        return string.encode('UTF-8')

def start_thread(func, daemon=True, args=None, kwargs=None):
    if args is None:
        args = ()
    if kwargs is None:
        kwargs = {}
    t = threading.Thread(
        target=func,
        args=args,
        kwargs=kwargs,
        daemon=daemon,
    )
    t.start()
    return t

class ZmqError(Exception):
    def __init__(self, message):
        self.message = message


class ZmqTimeoutError(Exception):
    def __init__(self):
        super().__init__('Request Timed Out')


class ZmqSocket(object):
    """
        Wrapper around zmq socket, manages resources automatically
    """
    SOCKET_TYPES = {
        'PULL': zmq.PULL,
        'PUSH': zmq.PUSH,
        'PUB': zmq.PUB,
        'SUB': zmq.SUB,
        'REQ': zmq.REQ,
        'REP': zmq.REP,
        'ROUTER': zmq.ROUTER,
        'DEALER': zmq.DEALER,
        'PAIR': zmq.PAIR,
    }

    def __init__(self, *,
                 address=None,
                 host=None,
                 port=None,
                 socket_mode,
                 bind,
                 context=None,
                 verbose=True):
        """
        Attributes:
            address
            host
            port
            bind
            socket_mode
            socket_type

        Args:
            address: either specify address or (host and port), but not both
            host: "localhost" is translated to 127.0.0.1
                use "*" to listen to all incoming connections
            port: int
            socket_mode: zmq.PUSH, zmq.PULL, etc., or their string names
            bind: True -> bind to address, False -> connect to address (see zmq)
            context: Zmq.Context object, if None, client creates its own context
            verbose: set to True to print log messages
        """
        if address is None:
            # https://stackoverflow.com/questions/6024003/why-doesnt-zeromq-work-on-localhost
            assert host is not None and port is not None, \
                "either specify address or (host and port), but not both"
            if host == 'localhost':
                host = '127.0.0.1'
            address = "{}:{}".format(host, port)
        if '://' in address:
            self.address = address
        else:  # defaults to TCP
            self.address = 'tcp://' + address
        self.host, port = self.address.split('//')[1].split(':')
        self.port = int(port)

        if context is None:
            self._context = zmq.Context()
            self._owns_context = True
        else:
            self._context = context
            self._owns_context = False

        if isinstance(socket_mode, str):
            socket_mode = self.SOCKET_TYPES[socket_mode.upper()]
        self.socket_mode = socket_mode
        self.bind = bind
        self.established = False
        self._socket = self._context.socket(self.socket_mode)
        self._verbose = verbose

    def unwrap(self):
        """
        Get the raw underlying ZMQ socket
        """
        return self._socket

    def establish(self):
        """
            We want to allow subclasses to configure the socket before connecting
        """
        if self.established:
            raise RuntimeError('Trying to establish a socket twice')
        self.established = True
        if self.bind:
            if self._verbose:
                print('[{}] binding to {}'.format(self.socket_type, self.address))
            self._socket.bind(self.address)
        else:
            if self._verbose:
                print('[{}] connecting to {}'.format(self.socket_type, self.address))
            self._socket.connect(self.address)
        return self

    def __getattr__(self, attrname):
        """
        Delegate any unknown methods to the underlying self.socket
        """
        if attrname in dir(self):
            return object.__getattribute__(self, attrname)
        else:
            return getattr(self._socket, attrname)

    def __del__(self):
        if self.established:
            self._socket.close()
        if self._owns_context: # only terminate context when we created it
            self._context.term()

    @property
    def socket_type(self):
        reverse_map = {value: name for name, value in self.SOCKET_TYPES.items()}
        return reverse_map[self.socket_mode]


class ZmqPusher:
    def __init__(self, address=None, host=None, port=None,
                 serializer=None, hwm=42):
        self.socket = ZmqSocket(
            address=address, host=host, port=port,
            socket_mode=zmq.PUSH, bind=False
        )
        self.socket.set_hwm(hwm)
        self.serializer = serializer
        self.socket.establish()

    def push(self, data):
        data = str2bytes(self.serializer(data))
        self.socket.send(data)


class ZmqPuller:
    def __init__(self, address=None, host=None, port=None,
                 bind=True, deserializer=None):
        self.socket = ZmqSocket(
            address=address, host=host, port=port,
            socket_mode=zmq.PULL, bind=bind
        )
        self.deserializer = deserializer
        self.socket.establish()

    def pull(self):
        data = self.socket.recv()
        return self.deserializer(data)


class ZmqClient:
    """
    Send request and receive reply from ZmqServer
    """
    def __init__(self, address=None, host=None, port=None,
                 timeout=-1,
                 serializer=None,
                 deserializer=None,
                 name=''):
        """
        Args:
            address:
            host:
            port:
            timeout: how long do we wait for response, in seconds,
               negative means wait indefinitely
            serializer:
            deserializer:
        """
        self.timeout = timeout
        self.serializer = serializer
        self.deserializer = deserializer
        self.socket = ZmqSocket(
            address=address, host=host, port=port,
            socket_mode=zmq.REQ, bind=False
        )
        if self.timeout >= 0:
            self.socket.setsockopt(zmq.LINGER, 0)
        if name:
            self.socket.setsockopt(zmq.IDENTITY, str2bytes(name))
        self.socket.establish()

    def request(self, msg):
        """
        Requests to the earlier provided host and port for data.

        https://github.com/zeromq/pyzmq/issues/132
        We allow the requester to time out

        Args:
            msg: send msg to ZmqServer to request for reply

        Returns:
            reply data from ZmqServer

        Raises:
            ZmqTimeoutError if timed out
        """

        msg = str2bytes(self.serializer(msg))
        self.socket.send(msg)

        if self.timeout >= 0:
            poller = zmq.Poller()
            poller.register(self.socket.unwrap(), zmq.POLLIN)
            if poller.poll(self.timeout * 1000):
                rep = self.socket.recv()
                return self.deserializer(rep)
            else:
                raise ZmqTimeoutError()
        else:
            rep = self.socket.recv()
            return self.deserializer(rep)


class ZmqServer:
    def __init__(self, address=None, host=None, port=None,
                 serializer=None,
                 deserializer=None,
                 load_balanced=False,
                 context=None):
        """
        Args:
            host:
            port:
            load_balanced:
            serializer: serialize data before replying (sending)
            deserializer: deserialize data after receiving
            context:

        """
        self.serializer = serializer
        self.deserializer = deserializer
        self.socket = ZmqSocket(
            address=address,
            host=host,
            port=port,
            socket_mode=zmq.REP,
            bind=not load_balanced,
            context=context
        )
        self.socket.establish()
        self._thread = None
        self._next_step = 'recv'  # for error checking only

    def recv(self):
        """
        Warnings:
            DO NOT call recv() after you start an event_loop
        """
        if self._next_step != 'recv':
            raise ValueError('recv() and send() must be paired. You can only send() now')
        data = self.socket.recv()
        self._next_step = 'send'
        return self.deserializer(data)

    def send(self, msg):
        """
        Warnings:
            DO NOT call send() after you start an event_loop
        """
        if self._next_step != 'send':
            raise ValueError('send() and recv() must be paired. You can only recv() now')
        msg = str2bytes(self.serializer(msg))
        self.socket.send(msg)
        self._next_step = 'recv'

    def _event_loop(self, handler):
        while True:
            msg = self.recv()  # request msg from ZmqClient
            reply = handler(msg)
            self.send(reply)

    def start_event_loop(self, handler, blocking=False):
        """
        Args:
            handler: function that takes an incoming client message (deserialized)
                and returns a reply to client (before serializing)
            blocking: True to block the main program
                False to launch a thread in the background and immediately returns

        Returns:
            if non-blocking, returns the created thread
        """
        if blocking:
            self._event_loop(handler)
        else:
            if self._thread:
                raise RuntimeError('event loop is already running')
            self._thread = start_thread(self._event_loop)
            return self._thread


class ZmqAsyncServer:
    def __init__(self, address=None, host=None, port=None,
                 serializer=None,
                 deserializer=None,
                 load_balanced=False,
                 context=None):
        """
        Args:
            host:
            port:
            load_balanced:
            serializer: serialize data before replying (sending)
            deserializer: deserialize data after receiving
            context:

        """
        self.serializer = serializer
        self.deserializer = deserializer
        self.socket = ZmqSocket(
            address=address,
            host=host,
            port=port,
            socket_mode=zmq.ROUTER,
            bind=not load_balanced,
            context=context
        )
        self.socket.establish()

    def recv(self):
        """
        """
        try:
            address, _, data = self.socket.recv_multipart(flags=zmq.NOBLOCK)
            return address, self.deserializer(data)
        except zmq.Again as e:
            return None, None

    def send(self, address, msg):
        """
        """
        msg = self.serializer(msg)
        self.socket.send_multipart([address, b'', msg])
