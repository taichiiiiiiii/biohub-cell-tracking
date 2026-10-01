"""Synthetic pytest coverage for _terminate_owned_process in scripts/e27_motion_cost_run.py.

No real child processes, signals, IO or model code are involved.
"""

import signal
import subprocess

import pytest

import scripts.experiments.e27.e27_motion_cost_run as m


class FakeProcess:
    """Minimal stand-in for subprocess.Popen recording ordered kill/wait events."""

    def __init__(self, poll_result, wait_outcomes, events):
        self.pid = 424242
        self._poll_result = poll_result
        self._wait_outcomes = list(wait_outcomes)
        self._events = events

    def poll(self):
        self._events.append(('poll',))
        return self._poll_result

    def wait(self, timeout=None):
        self._events.append(('wait', timeout))
        outcome = self._wait_outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


@pytest.fixture
def signal_events(monkeypatch):
    """Shared ordered event log; os.killpg is replaced so no real signal is sent."""

    events = []

    def fake_killpg(pgid, sig, *args, **kwargs):
        events.append(('killpg', pgid, sig))

    monkeypatch.setattr(m.os, 'killpg', fake_killpg)
    return events


def test_none_proc_does_nothing(signal_events):
    proc = None

    m._terminate_owned_process(proc)

    assert signal_events == []


def test_already_exited_is_reaped_without_signals(signal_events):
    proc = FakeProcess(poll_result=0, wait_outcomes=[0], events=signal_events)

    m._terminate_owned_process(proc)

    assert signal_events == [('poll',), ('wait', 5)]


def test_sigterm_then_successful_wait(signal_events):
    proc = FakeProcess(
        poll_result=None, wait_outcomes=[-signal.SIGTERM], events=signal_events
    )

    m._terminate_owned_process(proc)

    assert signal_events == [
        ('poll',),
        ('killpg', 424242, signal.SIGTERM),
        ('wait', 5),
    ]


def test_sigterm_processlookup_still_reaps(signal_events, monkeypatch):
    def vanished(pgid, sig, *args, **kwargs):
        signal_events.append(('killpg', pgid, sig))
        raise ProcessLookupError()

    monkeypatch.setattr(m.os, 'killpg', vanished)
    proc = FakeProcess(poll_result=None, wait_outcomes=[0], events=signal_events)

    m._terminate_owned_process(proc)

    assert signal_events == [
        ('poll',),
        ('killpg', 424242, signal.SIGTERM),
        ('wait', 5),
    ]


def test_term_wait_timeout_escalates_to_sigkill(signal_events):
    timeout = subprocess.TimeoutExpired(cmd='ignored', timeout=5)
    proc = FakeProcess(
        poll_result=None,
        wait_outcomes=[timeout, -signal.SIGKILL],
        events=signal_events,
    )

    m._terminate_owned_process(proc)

    assert signal_events == [
        ('poll',),
        ('killpg', 424242, signal.SIGTERM),
        ('wait', 5),
        ('killpg', 424242, signal.SIGKILL),
        ('wait', 5),
    ]


def test_final_wait_timeout_propagates(signal_events):
    first = subprocess.TimeoutExpired(cmd='ignored', timeout=5)
    second = subprocess.TimeoutExpired(cmd='ignored', timeout=5)
    proc = FakeProcess(
        poll_result=None,
        wait_outcomes=[first, second],
        events=signal_events,
    )

    with pytest.raises(subprocess.TimeoutExpired):
        m._terminate_owned_process(proc)

    assert signal_events == [
        ('poll',),
        ('killpg', 424242, signal.SIGTERM),
        ('wait', 5),
        ('killpg', 424242, signal.SIGKILL),
        ('wait', 5),
    ]
