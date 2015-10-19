import base64
import hashlib
import re
import socket
import threading
import struct

MAGIC_STRING = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
RESPONSE_HEADERS = (
	"HTTP/1.1 101 Switching Protocols",
	"Upgrade: websocket",
	"Connection: Upgrade",
	"Sec-WebSocket-Accept: %s",
)

def stringToBits(string):
	bits = 0
	for char in string:
		bits << 8
		bits += ord(char)
	return bits

def bit(string, index):
	data = stringToBits(string) 
	return (data & (1 << index)) >> index

def bits(string, start, end):
	data = stringToBits(string)
	diff = end - start + 1
	mask = ((1 << diff) - 1) << start
	return (data & mask) >> start

class ClientConnection(threading.Thread):
	def __init__(self, socket, address):
		self.socket = socket
		self.address = address[0]
		self.port = address[1]
		self.id = "%s|%s" % (self.address, self.port)
		self.stop_running = False
		
		socket.settimeout(1.0)
		
		threading.Thread.__init__(self)
	
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
		self.socket.send(response)
	
	def cancel(self):
		self.stop_running = True
	
	def send(self, message):
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
		print "sending frame: %s" % frame
		self.socket.send(frame)
			
	
	def processFrame(self, frame_info):
		print "frame length: %d" % len(frame_info)
		print "frame from %s: %s" % (self.id, frame_info)
		print "FIN is: %d" % bit(frame_info[0], 7)
		print "MASK is: %d" % bit(frame_info[1], 7)
		opcode = bits(frame_info[0], 0, 3)
		print "opcode is: %d" % opcode
		payload_length = bits(frame_info[1], 0, 6)
		
		if opcode == 8:
			self.socket.close()
			return
		
		if payload_length == 126:
			payload_length = struct.unpack('>H', self.socket.recv(2))
		elif payload_length == 127:
			payload_length = struct.unpack('>L', self.socket.recv(8))
		
		print "payload len is: %d" % payload_length
		
		mask = self.socket.recv(4)
		print "mask is: %s" % mask
		encoded = self.socket.recv(payload_length)
		message = []
		for i, char in enumerate(encoded):
			message.append(chr(ord(char) ^ ord(mask[i % 4])))
		message = "".join(message)
		
		print "message received: %s" % message
		self.send("This is a response!")	
	
	def run(self):
		self.handshake()
		
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
				
		print "exiting connection thread for %s" % self.id

if __name__ == "__main__":
	serversocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	serversocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

	serversocket.bind(('', 8888))
	serversocket.listen(5)

	connections = {}
	try:
		while True:
			print "listening..."

			(clientsocket, address) = serversocket.accept()

			print "Accepted connection from: " + str(address)
			connection = ClientConnection(clientsocket, address)
			connections["%s|%s" % (address[0], address[1])] = connection
			connection.start()
	except KeyboardInterrupt:
		pass
		
	for c in connections.values(): c.cancel()
    
