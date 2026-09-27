"""Optional Eval Workbench tracing. If the SDK is not installed these are harmless no-ops."""
try:
    from eval_workbench import Client, span, trace
except ImportError:
    from contextlib import contextmanager

    Client = None

    class _Handle:
        def set(self, **attrs):
            pass

    @contextmanager
    def span(name, kind="other", **attrs):
        yield _Handle()

    def trace(fn=None, **kwargs):
        return fn if callable(fn) else (lambda f: f)

__all__ = ["Client", "span", "trace"]
