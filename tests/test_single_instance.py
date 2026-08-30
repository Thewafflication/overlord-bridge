import uuid

import pytest

from modules.single_instance import AlreadyRunningError, SingleInstance


def test_only_one_instance_can_hold_a_named_lock():
    name = f"overlord-test-{uuid.uuid4().hex}"
    first = SingleInstance(name)
    second = SingleInstance(name)
    first.acquire()
    try:
        with pytest.raises(AlreadyRunningError):
            second.acquire()
    finally:
        first.release()


def test_released_singleton_can_be_acquired_again():
    name = f"overlord-test-{uuid.uuid4().hex}"
    first = SingleInstance(name)
    first.acquire()
    first.release()

    replacement = SingleInstance(name)
    replacement.acquire()
    replacement.release()
