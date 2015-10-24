import base64
import hashlib
import re
import socket
import threading
import struct
import Queue

MAGIC_STRING = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
RESPONSE_HEADERS = (
    "HTTP/1.1 101 Switching Protocols",
    "Upgrade: websocket",
    "Connection: Upgrade",
    "Sec-WebSocket-Accept: %s",
)
TIMEOUT = 1.0


class Server:
    def __init__(self, port, groups):
        self.GROUPS = groups
    
    def onConnect(self, address, port):
        pass
    
    def onClose(self, address, port):
        pass
    
    def onMessage(self, message, address, port):
        pass
    
    def close(self, port):
        self.GROUPS[port].cancel()
    
    def send(self, message, port):
        self.GROUPS[port].writer.send(message)
    
    def sendToAll(self, message):
        for group in self.GROUPS:
            group.writer.send(message)
    
    def sendToOthers(self, message, port):
        for other_port in self.GROUPS.keys():
            if other_port != port:
                self.GROUPS[other_port].writer.send(message)

class ConnectionGroup:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
    
    def cancel(self):
        self.reader.cancel()
        self.writer.cancel()
    
    def start(self):
        self.reader.start()
        self.writer.start()

class ConnectionThread(threading.Thread):
    def __init__(self, socket, address, port, groups):
        self.socket = socket
        self.groups = groups
        self.address = address
        self.port = int(port)
        self.id = "%s:%s" % (self.address, self.port)
        self.stop_running = False
        
        socket.settimeout(TIMEOUT)
        
        threading.Thread.__init__(self)
    
    def cancel(self):
        self.stop_running = True
    
    def shutdown(self):
        self.group.cancel()
        if self.port in self.groups: del self.groups[self.port]
        self.socket.close()

class Writer(ConnectionThread):
    def __init__(self, socket, address, port, groups):
        self.queue = Queue.Queue()
        
        ConnectionThread.__init__(self, socket, address, port, groups)
    
    def send(self, message):
        self.queue.put({'mode': 'frame', 'text': message})
    
    def sendRaw(self, message):
        self.queue.put({'mode': 'raw', 'text': message})
    
    def _sendFrame(self, message):
        frame = chr(0b10000001)
        
        length = len(message)
        if length <= 125:
            frame += struct.pack('>B', length)
        elif length <= 2**16:
            frame += struct.pack('>B', 126)
            frame += struct.pack('>H', length)
        else:
            frame += struct.pack('>B', 127)
            frame += struct.pack('>L', length)
        
        frame += message
        bytes_sent = 0
        try:
            bytes_sent = self.socket.send(frame)
        except:
            self.cancel()
        return bytes_sent
    
    def run(self):
        self.group = self.groups[self.port]
        while not self.stop_running:
            try:
                message = self.queue.get(True, TIMEOUT)
            except Queue.Empty:
                continue
            except:
                break
            
            if message['mode'] == 'frame':
                sent_bytes = self._sendFrame(message['text'])
                if sent_bytes == 0: break
            else:
                try:
                    self.socket.send(message['text'])
                except:
                    print "Error sending raw message: %s" % message['text']
                    break
        
        self.shutdown()
        print "Exiting writer thread for %s" % self.id

class Reader(ConnectionThread):    
    def __init__(self, socket, address, port, groups, server):
        self.server = server
        self.payloads = []
        
        ConnectionThread.__init__(self, socket, address, port, groups)
    
    def stringToBits(self, string):
        bits = 0
        for char in string:
            bits << 8
            bits += ord(char)
        return bits

    def bit(self, string, index):
        data = self.stringToBits(string) 
        return (data & (1 << index)) >> index

    def bits(self, string, start, end):
        data = self.stringToBits(string)
        diff = end - start + 1
        mask = ((1 << diff) - 1) << start
        return (data & mask) >> start
    
    def parseWebsocketKey(self, request):
        match = re.search(r"Sec-WebSocket-Key: (.*)\r\n", request)
        if match:
            return match.group(1)
        else:
            raise ValueError("Couldn't parse websocket key")

    def acceptKey(self, websocket_key):
        digest = hashlib.sha1(websocket_key + MAGIC_STRING).digest()
        return base64.b64encode(digest)

    def response(self, key):
        return ("\r\n".join(RESPONSE_HEADERS) % key) + "\r\n\r\n"
        
    def handshakeResponse(self, request):
        return self.response(self.acceptKey(self.parseWebsocketKey(request)))
    
    def handshake(self):
        request = self.socket.recv(1024)
        print "received: \n" + request
        response = self.handshakeResponse(request)
        print "response: \n" + response
        self.group.writer.sendRaw(response)
    
    def processFrame(self, frame_info):
        fin = self.bit(frame_info[0], 7)
        masked = self.bit(frame_info[1], 7)
        opcode = self.bits(frame_info[0], 0, 3)
        
        error = ""
        if not masked:
            error = "Unmasked message received. Disconnecting."
        elif opcode == 8:
            error = "Disconnect opcode received (8). Closing connection."
        elif opcode not in (0, 1):
            error = "Invalid opcode %d received (binary data is not yet supported). Disconnecting." % opcode
        
        if error:
            print error
            self.socket.close()
            return
        
        payload_length = self.bits(frame_info[1], 0, 6)
        if payload_length == 126:
            payload_length = struct.unpack('>H', self.socket.recv(2))[0]
        elif payload_length == 127:
            payload_length = struct.unpack('>Q', self.socket.recv(8))[0]
                
        mask = self.socket.recv(4)
        encoded = self.socket.recv(payload_length)
        message = []
        for i, char in enumerate(encoded):
            message.append(chr(ord(char) ^ ord(mask[i % 4])))
        message = "".join(message)
        
        self.payloads.append(message)
        if fin:
            self.server.onMessage("".join(self.payloads), self.address, self.port)
            self.payloads = []
    
    def run(self):
        self.group = self.groups[self.port]
        self.handshake()
        self.server.onConnect(self.address, self.port)
        
        while not self.stop_running:
            try:
                message = self.socket.recv(2)
            except socket.timeout:
                continue
            except:
                break
            
            if len(message):
                self.processFrame(message)
            else:
                break
        
        self.server.onClose(self.address, self.port)
        self.shutdown()
        print "Exiting reader thread for %s" % self.id

class Listener:
    def __init__(self, port, server_class):
        self.port = port
        self.server_class = server_class
    
    def start(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', self.port))
        sock.listen(5)
        print "listening on port %d..." % self.port

        groups = {}     # map of port => ConnectionGroup
        try:
            while True:
                (clientsocket, address) = sock.accept()
                (address, port) = address
                print "Accepted connection from: %s:%s" % (address, port)
                
                connection = self.server_class(port, groups)
                reader = Reader(clientsocket, address, port, groups, connection)
                writer = Writer(clientsocket, address, port, groups)
                group = ConnectionGroup(reader, writer)
                groups[port] = group
                group.start()
        except KeyboardInterrupt:
            pass
            
        for group in groups.values(): group.cancel()

if __name__ == "__main__":
    serversocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    serversocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    serversocket.bind(('', PORT))
    serversocket.listen(5)
    print "listening on port %d..." % PORT

    groups = {}     # map of port => ConnectionGroup
    try:
        while True:
            (clientsocket, address) = serversocket.accept()
            (address, port) = address
            print "Accepted connection from: %s:%s" % (address, port)
            
            connection = ClientConnection(port, groups)
            reader = Reader(clientsocket, address, port, groups, connection)
            writer = Writer(clientsocket, address, port, groups)
            group = ConnectionGroup(reader, writer)
            groups[port] = group
            group.start()
    except KeyboardInterrupt:
        pass
        
    for group in groups.values(): group.cancel()
    
