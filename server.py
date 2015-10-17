import base64
import hashlib
import re
import socket
import threading

MAGIC_STRING = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
RESPONSE_HEADERS = (
	"HTTP/1.1 101 Switching Protocols",
	"Upgrade: websocket",
	"Connection: Upgrade",
	"Sec-WebSocket-Accept: %s",
)

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
	
	def run(self):
		self.handshake()
		
		while not self.stop_running:
			try:
				message = self.socket.recv(2**14)
			except socket.timeout:
				continue
			
			if len(message):
				print "message from %s: %s" % (self.id, message)
			else:
				break
				
		print "exiting connection thread"

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
    
