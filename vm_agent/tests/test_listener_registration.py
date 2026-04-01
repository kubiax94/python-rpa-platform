import unittest

from pyee import EventEmitter

from shared.network.events.example_event import AuthResultData
from vm_agent.src.core.listener_registration import bind_registered_listeners, register_listener


class AuthResultEventStub:
    type = "auth_result"

    def register_listener(self, bus, callback, once=True):
        if once:
            bus.once(self.type, callback)
        else:
            bus.on(self.type, callback)


class ListenerOwner:
    def __init__(self):
        self.received = []

    @register_listener(AuthResultEventStub, once=False)
    def handle_auth(self, payload):
        self.received.append(payload)


class ListenerRegistrationTests(unittest.TestCase):
    def test_bind_registered_listeners_registers_decorated_methods(self):
        bus = EventEmitter()
        owner = ListenerOwner()

        bind_registered_listeners(bus, owner)
        payload = AuthResultData(status="ok", access_token="token-1")
        bus.emit("auth_result", payload)

        self.assertEqual(owner.received, [payload])


if __name__ == "__main__":
    unittest.main()