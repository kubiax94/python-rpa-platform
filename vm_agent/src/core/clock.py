import time

class Clock:
    # Czas rzeczywisty (systemowy)
    real_delta_time: float = 0.0
    real_elapsed_time: float = 0.0
    
    # Czas interwałowy (logiczny - na podstawie ticków lifecycle)
    _interval: float = 0.0
    _tick_count: int = 0

    _last_real_ts: float = 0.0
    _start_real_ts: float = 0.0

    @classmethod
    def start(cls, interval: float):
        """Inicjalizacja zegara z konkretnym interwałem z LifecycleManagera."""
        cls._interval = interval
        cls._start_real_ts = time.perf_counter()
        cls._last_real_ts = cls._start_real_ts
        cls._tick_count = 0

    @classmethod
    def update(cls):
        """Wywoływane raz na każdy tik pętli Lifecycle."""
        # Update czasu rzeczywistego
        now = time.perf_counter()
        cls.real_delta_time = now - cls._last_real_ts
        cls.real_elapsed_time = now - cls._start_real_ts
        cls._last_real_ts = now
        
        # Update czasu logicznego (zliczamy ticki)
        cls._tick_count += 1

    @classmethod
    def get_time(cls) -> float:
        """Zwraca 'czas logiczny' - przeliczony z liczby interwałów."""
        return cls._tick_count * cls._interval

    @classmethod
    def get_real_time(cls) -> float:
        """Zwraca faktyczny czas systemowy od startu."""
        return cls.real_elapsed_time

    @property
    def tick_count(cls) -> int:
        return cls._tick_count