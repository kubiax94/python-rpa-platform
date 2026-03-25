from __future__ import annotations

import asyncio
import logging
from typing import List

from vm_agent.src.core.clock import Clock
from vm_agent.src.core.ilifecycle import ILifeCycle

logger = logging.getLogger(__name__)

logging.basicConfig(
    filename=r"C:\VmAgent\agent.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

class LifecycleManager:
    """
    Manages lifecycle components.
    Handles registration, starting, ticking, and stopping.
    """
    
    def __init__(self, tick_interval: float = 1.0):
        self.tick_interval = tick_interval
        self._current_tick = 0
        self._components: List[ILifeCycle] = []
        self._running = False
        self._task: asyncio.Task | None = None
    
    def register(self, component: ILifeCycle) -> None:
        """Register a lifecycle component"""
        if component in self._components:
            logger.warning(f"Component {component.get_name()} already registered")
            return
        
        self._components.append(component)
        logger.info(f"Registered to life cycle: {component.get_name()}")
        
        # If already running, start immediately
        if self._running:
            try:
                component.on_start()
            except Exception as e:
                logger.exception(f"Error starting {component.get_name()}: {e}")
    
    def unregister(self, component: ILifeCycle) -> None:
        """Unregister a component"""
        if component not in self._components:
            return
        
        try:
            component.on_stop()
        except Exception as e:
            logger.exception(f"Error stopping {component.get_name()}: {e}")
        
        self._components.remove(component)
        logger.info(f"Unregistered: {component.get_name()}")
    
    async def start(self) -> None:
        """Start all components and begin lifecycle loop"""
        if self._running:
            logger.warning("LifecycleManager already running")
            return
        
        logger.info("Starting LifecycleManager")
        self._running = True
        
        # Start all components
        for component in self._components:
            try:
                component.on_start()
                logger.info(f"Started: {component.get_name()}")
            except Exception as e:
                logger.exception(f"Error starting {component.get_name()}: {e}")
        
        # Start tick loop
        self._task = asyncio.create_task(self._tick_loop())
        logger.info(f"LifecycleManager started with {len(self._components)} components")
    
    async def _tick_loop(self) -> None:
        """Main tick loop"""
        logger.info("Lifecycle tick loop started")
        
        while self._running:
            try:
                # Tick all components
                for component in self._components:
                    try:
                        component.on_tick()
                    except Exception as e:
                        logger.exception(f"Error in {component.get_name()}.on_tick(): {e}")
                        
                        # Check health
                        if not component.is_healthy():
                            logger.error(f"Component {component.get_name()} is unhealthy!")
                
                # Sleep until next tick
                Clock.update()
                await asyncio.sleep(self.tick_interval)
                
            
            except asyncio.CancelledError:
                logger.info("Tick loop cancelled")
                break
            except Exception as e:
                logger.exception(f"Tick loop error: {e}")
                await asyncio.sleep(1.0)
        
        logger.info("Tick loop stopped")
    
    async def stop(self) -> None:
        """Stop all components and lifecycle loop"""
        if not self._running:
            return
        
        logger.info("Stopping LifecycleManager")
        self._running = False
        
        # Cancel tick loop
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        # Stop all components
        for component in self._components:
            try:
                component.on_stop()
                logger.info(f"Stopped: {component.get_name()}")
            except Exception as e:
                logger.exception(f"Error stopping {component.get_name()}: {e}")
        
        logger.info("LifecycleManager stopped")
    
    def get_status(self) -> dict:
        """Get status of all components"""
        return {
            "running": self._running,
            "tick_interval": self.tick_interval,
            "component_count": len(self._components),
            "components": [comp.get_status() for comp in self._components]
        }