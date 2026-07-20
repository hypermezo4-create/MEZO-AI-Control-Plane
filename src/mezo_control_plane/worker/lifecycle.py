import asyncio


class WorkerLifecycle:
    def __init__(self) -> None:
        self._stopping = asyncio.Event()

    def stop(self) -> None:
        self._stopping.set()

    @property
    def accepting_work(self) -> bool:
        return not self._stopping.is_set()
