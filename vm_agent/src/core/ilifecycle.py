# LifceCycle event for application componen
from abc import ABC, abstractmethod

class ILifeCycle(ABC):

    @abstractmethod
    def on_start(self):
        pass

    @abstractmethod    
    def on_tick(self):  
        pass  

    @abstractmethod
    def on_stop(self):
        pass

    @abstractmethod
    def get_name(self) -> str:
        pass
    
    @abstractmethod
    def is_healthy(self) -> bool:
        pass
