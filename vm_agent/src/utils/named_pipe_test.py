import win32file
import win32pipe
import struct
import pywintypes
import time

PIPE_NAME = r'\\.\pipe\sample_agent_pipe'

def send_logon_command(username, password, domain ,timeout_sec=30):
    # 1. Przygotowanie danych (UTF-16LE)
    user_bytes = username.encode('utf-16le')[:126].ljust(128, b'\0')
    pass_bytes = password.encode('utf-16le')[:126].ljust(128, b'\0')
    dom_b = domain.encode('utf-16le')[:126].ljust(128, b'\0')  #  Pusta domena dla lokalnego konta
    
    # Budujemy paczkę: op(1b), res(1b), len(2b), data(1024b)
    op_code = 0x00
    combined_data = user_bytes + pass_bytes + dom_b
    data_len = len(combined_data)
    
    payload = struct.pack("<BBH384s", 
                         op_code, 
                         0, 
                         data_len, 
                         combined_data)
    print(f"[*] Rozpoczynam nasłuch na potok: {PIPE_NAME} (timeout: {timeout_sec}s)")
    start_time = time.time()

    while True:
        # Sprawdzamy czy nie minął czas
        if (time.time() - start_time) > timeout_sec:
            print("[-] Błąd: Timeout. Serwer logowania nie pojawił się.")
            return False

        try:
            # KLUCZ: Czekamy aż Windows zarejestruje Pipe'a
            # WaitNamedPipe czeka aż instancja będzie dostępna
            win32pipe.WaitNamedPipe(PIPE_NAME, 2000) # Czekaj 2 sekundy w każdej iteracji
            
            # Jeśli WaitNamedPipe przeszło, otwieramy uchwyt
            handle = win32file.CreateFile(
                PIPE_NAME,
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0, None,
                win32file.OPEN_EXISTING,
                0, None
            )

            win32file.WriteFile(handle, payload)
            print(f"[+] Sukces! Dane wysłane do LogonUI.")
            win32file.CloseHandle(handle)
            return True

        except pywintypes.error as e:
            if e.winerror == 2: # File not found (Pipe jeszcze nie istnieje)
                print("[.] Serwer jeszcze nie wstał, ponawiam...")
                time.sleep(1) # Mały cooldown przed następną próbą
                continue
            elif e.winerror == 231: # Pipe is busy (Ktoś inny się podłączył)
                print("[.] Potok zajęty, czekam...")
                time.sleep(0.5)
                continue
            elif e.winerror == 5:
                print("[-] Błąd: Access Denied. Sprawdź DACL w C++ (LogonUI isolation).")
                return False
            else:
                print(f"[-] Niespodziewany błąd: {e.strerror}")
                return False
