import threading
import serial


def open_port(port, baud):
    # Configure before open; do not pulse control lines or reset input buffers.
    # Drivers/OS can still glitch lines on open; physical behavior needs retest.
    device = serial.Serial(port=None, baudrate=baud, timeout=0.1, write_timeout=1,
                           rtscts=False, dsrdtr=False)
    device.dtr = False
    device.rts = False
    device.port = port
    device.open()
    return device


class Receiver:
    def __init__(self, device, engine):
        self.device, self.engine = device, engine
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, name='node01-rx', daemon=True)

    def start(self):
        self.thread.start()

    def run(self):
        while not self.stop_event.is_set():
            try:
                data = self.device.read(min(max(self.device.in_waiting, 1), 4096))
                if data:
                    self.engine.receive(data, self.engine.clock.sample())
                if self.engine.fatal:
                    return
            except Exception as error:
                if not self.stop_event.is_set():
                    self.engine.disconnected(error)
                return

    def stop(self):
        self.stop_event.set()
        self.thread.join(2)
        try:
            self.device.close()
        finally:
            self.thread.join(1)
        if self.thread.is_alive():
            self.engine._fault(RuntimeError('串口接收线程未终止；本次证据不能称完整'))
