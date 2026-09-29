from app.pipeline import memory


def test_windows_cleanup_does_not_load_posix_libc(monkeypatch):
    collected = []
    monkeypatch.setattr(memory.sys, "platform", "win32")
    monkeypatch.setattr(memory.gc, "collect", lambda: collected.append(True))

    def forbidden_load(*args):
        raise AssertionError("POSIX libc must not be loaded on Windows")

    monkeypatch.setattr(memory.ctypes, "CDLL", forbidden_load)
    memory.release_cpu_memory()
    assert collected == [True]


def test_linux_without_malloc_trim_can_still_unload(monkeypatch):
    monkeypatch.setattr(memory.sys, "platform", "linux")
    monkeypatch.setattr(memory.ctypes, "CDLL", lambda _: object())
    memory.release_cpu_memory()
