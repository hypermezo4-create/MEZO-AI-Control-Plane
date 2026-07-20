from mezo_control_plane.worker.lifecycle import WorkerLifecycle


def request_shutdown(lifecycle: WorkerLifecycle) -> None:
    lifecycle.stop()
