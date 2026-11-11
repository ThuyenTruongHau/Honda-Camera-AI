"""Task-local observations used by a business decision, copied on every write."""
from contextvars import ContextVar

observations = ContextVar("camera_decision_observations", default=None)


def remember(point, token):
    current = observations.get()
    if current is not None:
        updated = dict(current)
        updated[point] = token
        observations.set(updated)
