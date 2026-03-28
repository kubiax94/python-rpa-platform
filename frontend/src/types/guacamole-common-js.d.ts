declare module "guacamole-common-js" {
  interface GuacamoleStatus {
    code?: number;
    message?: string;
  }

  interface GuacamoleDisplay {
    getElement(): HTMLElement;
    getWidth(): number;
    getHeight(): number;
    scale(scale: number): void;
    onresize?: ((width: number, height: number) => void) | null;
  }

  interface GuacamoleTunnel {
    onstatechange?: ((state: number) => void) | null;
    onerror?: ((status: GuacamoleStatus) => void) | null;
    receiveTimeout?: number;
    unstableThreshold?: number;
    disconnect(): void;
  }

  interface GuacamoleClient {
    onstatechange?: ((state: number) => void) | null;
    onerror?: ((status: GuacamoleStatus) => void) | null;
    connect(data?: string): void;
    disconnect(): void;
    getDisplay(): GuacamoleDisplay;
    sendMouseState(state: unknown, applyDisplayScale?: boolean): void;
    sendKeyEvent(pressed: number, keysym: number): void;
    sendSize(width: number, height: number, dpi?: number): void;
  }

  interface GuacamoleMouse {
    onmousedown?: ((state: unknown) => void) | null;
    onmouseup?: ((state: unknown) => void) | null;
    onmousemove?: ((state: unknown) => void) | null;
  }

  interface GuacamoleKeyboard {
    onkeydown?: ((keysym: number) => boolean | void) | null;
    onkeyup?: ((keysym: number) => boolean | void) | null;
  }

  interface GuacamoleTouchpad {
    onmousedown?: ((state: unknown) => void) | null;
    onmouseup?: ((state: unknown) => void) | null;
    onmousemove?: ((state: unknown) => void) | null;
  }

  interface GuacamoleTouchscreen {
    onmousedown?: ((state: unknown) => void) | null;
    onmouseup?: ((state: unknown) => void) | null;
    onmousemove?: ((state: unknown) => void) | null;
  }

  interface GuacamoleMouseConstructor {
    new (element: Element): GuacamoleMouse;
    Touchpad: new (element: Element) => GuacamoleTouchpad;
    Touchscreen: new (element: Element) => GuacamoleTouchscreen;
  }

  interface GuacamoleClientConstructor {
    new (tunnel: GuacamoleTunnel): GuacamoleClient;
    State: {
      IDLE: number;
      CONNECTING: number;
      WAITING: number;
      CONNECTED: number;
      DISCONNECTING: number;
      DISCONNECTED: number;
    };
  }

  interface GuacamoleNamespace {
    Client: GuacamoleClientConstructor;
    HTTPTunnel: new (url: string) => GuacamoleTunnel;
    WebSocketTunnel: new (url: string) => GuacamoleTunnel;
    ChainedTunnel: new (...tunnels: GuacamoleTunnel[]) => GuacamoleTunnel;
    Mouse: GuacamoleMouseConstructor;
    Keyboard: new (target: Document | HTMLElement) => GuacamoleKeyboard;
  }

  const Guacamole: GuacamoleNamespace;
  export default Guacamole;
}