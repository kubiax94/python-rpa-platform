import asyncio
from enum import Enum
import logging
import types
from pyee.base import EventEmitter
from websockets import ClientConnection, ConnectionClosed
from websockets.asyncio.client import connect

from shared.core.iprocesable import IProcesable
from shared.network.iconnection import IConnection
from shared.protocol.net_headers import NetHeaders

class AgentConnectionStatus(Enum):
    INIT = -1
    DISCONNECTED = 0
    CONNECTING = 1
    CONNECTED = 2
    ERROR = 3
    RECONNECTING = 4
    STOP = 666

# Base NetConnection for probably only agent communication, but
# this is low level stuff agnet logic dont need to that 
class AgentConnection(IConnection): 
    def __init__(self, config):
        self.url = config.get("url", "ws://192.168.1.10:8765/ws")
        self._status: AgentConnectionStatus = AgentConnectionStatus.INIT
        self.secret = config.get("secret")
        self.bootstrap_token = config.get("bootstrap_token")
        self.fatal_error_reason: str | None = None
        self._ws : ClientConnection = None
        #Task for main msg loop from server
        self._read_loop_task: asyncio.Task = None
        self.client : IProcesable = None
        
        self._retry_count = 0
        self._retry_delay = config.get("retry_delay", 2)  # 
    
    async def close(self):
        if self._ws:
            await self._ws.close()
            self._ws = None
            self._status = AgentConnectionStatus.DISCONNECTED
            logging.info(f"WebSocket connection to {self.url} closed")
        if self._read_loop_task:
            self._read_loop_task.cancel()
            try:
                await self._read_loop_task
            except asyncio.CancelledError:
                pass
            self._read_loop_task = None

    def update_credentials(self, *, secret: str | None = None, bootstrap_token: str | None = None):
        self.secret = secret
        self.bootstrap_token = bootstrap_token

    def stop(self, reason: str | None = None):
        self.fatal_error_reason = reason
        self._status = AgentConnectionStatus.STOP

    def get_fatal_error_reason(self) -> str | None:
        return self.fatal_error_reason

    def get_status(self) -> AgentConnectionStatus:
        return self._status
    
    # If you want to defian something to process it's need to inheret from i Porcesable,
    # rest logic can be custom.
    async def open(self, client: IProcesable):  
        try:
            auth_secret = self.secret or self.bootstrap_token
            headers = NetHeaders.add_bearer_auth_header(auth_secret) if auth_secret else None

            if(self._ws and self._status == AgentConnectionStatus.CONNECTED):
                logging.debug(f"WebSocket connection to {self.url} already established")
                return

            if self._ws:
                await self.close()
            
            self._status = AgentConnectionStatus.CONNECTING
            logging.info(f"Connecting to {self.url}...")
            additional_headers = None
            if headers and headers.authorization:
                additional_headers = {"Authorization": headers.authorization}
            self._ws = await connect(self.url, additional_headers=additional_headers)
            self.client = client
            self._status = AgentConnectionStatus.CONNECTED

            if self._read_loop_task is None or self._read_loop_task.done():
                self._read_loop_task = asyncio.create_task(self._read_loop())
            
            self._retry_count = 0

            logging.info(f"WebSocket connection opened to {self.url}")

        except Exception as e:
            self._status = AgentConnectionStatus.ERROR
            logging.error(f"Failed to connect to {self.url}: {e}")
            raise

    async def reconnect(self):
        if self._status == AgentConnectionStatus.RECONNECTING:
            logging.warning("Already reconnecting, aborting duplicate call")
            return
        
        logging.info(f"Reconnecting to {self.url}...")
        
        while self._status != AgentConnectionStatus.CONNECTED:
            try:
                await self.close()
                await self.open(self.client)
                logging.info(f"Reconnected on attempt {self._retry_count}")
                return
            
            except Exception as e:
                self._status = AgentConnectionStatus.RECONNECTING
                self._retry_count += 1
                logging.error(f"Reconnect attempt {self._retry_count} failed: {e}")
                await asyncio.sleep(self._retry_delay)
                continue
                
        logging.error(f"Was not able to reconnect. Giving up.")
        self._status = AgentConnectionStatus.ERROR

    async def send(self, data: str | bytes):
        if self._status == AgentConnectionStatus.CONNECTING:
            logging.warning("Cannot send data while connecting")
            return
        if self._status != AgentConnectionStatus.CONNECTED or not self._ws:
            raise RuntimeError("WebSocket connection is not open")
        
        try:
            logging.debug(f"Sending data: {data}")
            await self._ws.send(data)
        except Exception as e:
            logging.error(f"Failed to send data: {e}")
            raise
    # Starting recv loop as async task
    def read(self) -> asyncio.Task:
        return asyncio.create_task(self._read_loop())

    async def _read_loop(self):
        if not self._ws:
            raise RuntimeError("WebSocket is not open. Call open() first.")
        try:
            while self._status == AgentConnectionStatus.CONNECTED:
                msg = await self._ws.recv()
                if msg is None:
                    break
                if self.client:
                    try:
                        logging.debug(f"Received message: {msg}")
                        await self.client.process(msg)
                    except Exception as e:
                        logging.error(f"Client processing error: {e}")
        except ConnectionClosed as e:
            close_code = getattr(e, "code", None) or getattr(getattr(e, "rcvd", None), "code", None)
            close_reason = getattr(e, "reason", None) or getattr(getattr(e, "rcvd", None), "reason", None) or str(e)
            logging.warning(f"Connection closed: {e}")
            if close_code in (4401, 4403):
                self.stop(close_reason or "authentication failed")
            else:
                self._status = AgentConnectionStatus.ERROR
            #await self.reconnect()                    
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logging.error(f"Error while reading from {self.url}: {e}")
            self._status = AgentConnectionStatus.ERROR
        finally:
            self._read_loop_task = None

                
