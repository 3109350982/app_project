# task_scheduler.py
import asyncio
from typing import Dict, Any

from browser_manager import BrowserManager
from data_storage import DataStorage
from license_client import LicenseClient

from services.xhs_collector import XHSCollectorService
from services.xhs_commenter import XHSCommenterService
from services.xhs_listener import XHSListenerService


class TaskScheduler:
    def __init__(
        self,
        browser_manager: BrowserManager,
        storage: DataStorage,
        license_client: LicenseClient,
    ):
        self.browser_manager = browser_manager
        self.storage = storage
        self.license_client = license_client

        self.services: Dict[str, Any] = {}
        self.tasks: Dict[str, asyncio.Task] = {}
        self._loop_running = True

        self._register_services()

    def _register_services(self):
        self.services["XHSCollectorService"] = XHSCollectorService(
            self.browser_manager, self.storage
        )
        self.services["XHSCommenterService"] = XHSCommenterService(
            self.browser_manager, self.storage
        )
        self.services["XHSListenerService"] = XHSListenerService(
            self.browser_manager, self.storage
        )

    async def start_service(self, name: str, **kwargs) -> bool:
        svc = self.services.get(name)
        if svc is None:
            return False
        if name in self.tasks and not self.tasks[name].done():
            return True
        task = asyncio.create_task(svc.run(**kwargs))
        self.tasks[name] = task
        return True

    async def stop_service(self, name: str):
        svc = self.services.get(name)
        if svc is not None:
            await svc.stop()
        t = self.tasks.get(name)
        if t is not None:
            t.cancel()
            try:
                await t
            except Exception:
                pass
            self.tasks.pop(name, None)

    async def shutdown_all(self):
        for name in list(self.tasks.keys()):
            await self.stop_service(name)
        try:
            await self.browser_manager.close()
        except Exception:
            pass

    async def shutdown_if_expired(self):
        if not self.license_client.status().get("valid"):
            await self.shutdown_all()

    async def run_loop(self):
        while True:
            await asyncio.sleep(1)
            if not self.license_client.status().get("valid"):
                await self.shutdown_all()
