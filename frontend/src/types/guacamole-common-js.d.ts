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
    showCursor(shown: boolean): void;
    onresize?: ((width: number, height: number) => void) | null;
  }

  interface GuacamoleTunnel {
    onstatechange?: ((state: number) => void) | null;
    onerror?: ((status: GuacamoleStatus) => void) | null;
    receiveTimeout?: number;
    unstableThreshold?: number;
    disconnect(): void;
  }

  interface GuacamoleOutputStream {
    index: number;
    sendBlob(data: string): void;
    sendEnd(): void;
  }

  interface GuacamoleInputStream {
    sendAck(message: string, code: number): void;
    onblob?: ((data: string) => void) | null;
    onend?: (() => void) | null;
  }

  interface GuacamoleStringWriter {
    onack?: ((status: GuacamoleStatus) => void) | null;
    sendText(text: string): void;
    sendEnd(): void;
  }

  interface GuacamoleStringReader {
    ontext?: ((text: string) => void) | null;
    onend?: (() => void) | null;
  }

  interface GuacamoleBlobWriter {
    onack?: ((status: GuacamoleStatus) => void) | null;
    oncomplete?: ((blob: Blob) => void) | null;
    onprogress?: ((blob: Blob, offset: number) => void) | null;
    sendBlob(blob: Blob): void;
    sendEnd(): void;
  }

  interface GuacamoleBlobReader {
    onprogress?: ((length: number) => void) | null;
    onend?: (() => void) | null;
    getLength(): number;
    getBlob(): Blob;
  }

  interface GuacamoleClient {
    onstatechange?: ((state: number) => void) | null;
    onerror?: ((status: GuacamoleStatus) => void) | null;
    onrequired?: ((parameters: string[]) => void) | null;
    onargv?: ((stream: GuacamoleInputStream, mimetype: string, name: string) => void) | null;
    onclipboard?: ((stream: GuacamoleInputStream, mimetype: string) => void) | null;
    onfile?: ((stream: GuacamoleInputStream, mimetype: string, filename: string) => void) | null;
    connect(data?: string): void;
    disconnect(): void;
    getDisplay(): GuacamoleDisplay;
    createArgumentValueStream(mimetype: string, name: string): GuacamoleOutputStream;
    createFileStream(mimetype: string, filename: string): GuacamoleOutputStream;
    createClipboardStream(mimetype: string): GuacamoleOutputStream;
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
    BlobReader: new (stream: GuacamoleInputStream, mimetype: string) => GuacamoleBlobReader;
    BlobWriter: new (stream: GuacamoleOutputStream) => GuacamoleBlobWriter;
    StringWriter: new (stream: GuacamoleOutputStream) => GuacamoleStringWriter;
    StringReader: new (stream: GuacamoleInputStream) => GuacamoleStringReader;
    SessionRecording: new (recordingBlob: Blob | GuacamoleTunnel) => {
      onload?: (() => void) | null;
      onerror?: ((message: string) => void) | null;
      onabort?: (() => void) | null;
      onprogress?: ((duration: number, currentSize: number) => void) | null;
      onplay?: (() => void) | null;
      onpause?: (() => void) | null;
      onseek?: ((position: number, currentFrame: number, targetFrame: number) => void) | null;
      connect(data?: string): void;
      disconnect(): void;
      abort(): void;
      cancel(): void;
      getDisplay(): GuacamoleDisplay;
      isPlaying(): boolean;
      getPosition(): number;
      getDuration(): number;
      play(): void;
      pause(): void;
      seek(position: number, callback?: () => void): void;
    };
  }

  const Guacamole: GuacamoleNamespace;
  export default Guacamole;
}