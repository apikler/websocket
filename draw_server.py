import json

from websocketserver import Server, Listener

PORT = 8888

class EchoServer(Server):
    def onConnect(self, address, port):
        print "Connection from %s:%d" % (address, port)
    
    def onMessage(self, message, address, port):
        try:
            message = json.loads(message)
            coords = message['coords']
            x1 = float(coords[0])
            x2 = float(coords[1])
            if message['event'] not in ('down', 'up', 'move'):
                raise ValueError('Invalid event %s' % message['event'])
        except KeyError, ValueError:
            print "Invalid message!"
            return
        
        message['client'] = port
        self.sendToOthers(json.dumps(message), port)        
    
    def onClose(self, address, port):
        print "Disconnected: %s:%d" % (address, port)

if __name__ == "__main__":
    listener = Listener(PORT, EchoServer)
    listener.start()
