from backend.storage import get_repository


def get_runtime_repository():
    return get_repository("session_runtimes")
