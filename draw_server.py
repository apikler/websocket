from websocketserver import Server, Listener

PORT = 8888

class EchoServer(Server):
    def onConnect(self, address, port):
        print "Connection from %s:%d" % (address, port)
    
    def onMessage(self, message, address, port):
        print "Message from %d: %s" % (port, message)
    
    def onClose(self, address, port):
        print "Disconnected: %s:%d" % (address, port)

if __name__ == "__main__":
    listener = Listener(PORT, EchoServer)
    listener.start()
