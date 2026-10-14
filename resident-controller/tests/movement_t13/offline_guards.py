"""Fail closed if an offline test attempts networking or a nested process."""
from contextlib import ExitStack, contextmanager
import os
import socket
import subprocess
from unittest.mock import patch


def forbidden(*_args, **_kwargs):
    raise AssertionError('offline_wire_test_external_action_forbidden')


@contextmanager
def offline_python():
    with ExitStack() as stack:
        for name in ('create_connection', 'create_server', 'socketpair'):
            stack.enter_context(patch.object(socket, name, forbidden))
        for name in ('connect', 'connect_ex', 'bind', 'listen'):
            stack.enter_context(patch.object(socket.socket, name, forbidden))
        stack.enter_context(patch.object(socket, 'socket', forbidden))
        stack.enter_context(patch.object(subprocess, 'Popen', forbidden))
        for name in ('system', 'fork', 'forkpty', 'posix_spawn', 'posix_spawnp'):
            if hasattr(os, name):
                stack.enter_context(patch.object(os, name, forbidden))
        yield
