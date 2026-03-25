import collections
import win32evtlog

class EventLogScanner:
    def __init__(self, log_name="System", max_events=20):
        self.log_name = log_name
        self.max_events = max_events
        self.events = collections.deque(maxlen=max_events)
        self.last_record_number = None

    def scan(self):
        handle = win32evtlog.OpenEventLog(None, self.log_name)
        flags = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ
        events = win32evtlog.ReadEventLog(handle, flags, 0)
        for event in events:
            if self.last_record_number is None or event.RecordNumber > self.last_record_number:
                self.events.appendleft(event)
        if self.events:
            self.last_record_number = self.events[0].RecordNumber
        win32evtlog.CloseEventLog(handle)

    def get_last_events(self) -> list:
        return list(self.events)