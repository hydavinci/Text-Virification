from __future__ import annotations

import asyncio
from threading import Event, get_ident
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from text_verification.api.routes import jobs
from text_verification.application.errors import VerificationError
from text_verification.config import Settings
from text_verification.domain.jobs import JobStatus


@pytest.mark.parametrize("operation", ["recheck", "revision", "export", "events"])
def test_blocking_job_work_leaves_event_loop_responsive_and_propagates_errors(
    monkeypatch, operation,
):
    loop_thread = get_ident()
    entered = Event()
    released = Event()
    threads = []
    failure = VerificationError("backend_unavailable", "validation", "Unavailable.", True)

    def blocking(*args, **kwargs):
        threads.append(get_ident())
        entered.set()
        assert released.wait(1), "event loop could not release blocking work"
        raise failure

    async def payload(*args, **kwargs):
        if operation == "recheck":
            return jobs.JobRecheckRequest(text="test")
        return jobs.JobExportRequest(format="docx_reconstruction")

    monkeypatch.setattr(jobs, "read_bounded_form_model", payload)
    monkeypatch.setattr(jobs, "read_bounded_json_model", payload)
    monkeypatch.setattr(jobs, "SESSION_FACTORY_PROVIDER", lambda: object())
    monkeypatch.setattr(jobs, "_poll_job_state", blocking)

    async def disconnected():
        return False

    async def exercise():
        async def release():
            while not entered.is_set():
                await asyncio.sleep(0.001)
            released.set()

        releaser = asyncio.create_task(release())
        service = SimpleNamespace(recheck=blocking, persist=blocking, export=blocking)
        request = SimpleNamespace(is_disconnected=disconnected)
        job_id = uuid4()
        repository_threads = []

        def get_job(*args):
            repository_threads.append(get_ident())
            return SimpleNamespace(status=JobStatus.COMPLETED)

        repository = SimpleNamespace(
            get_job=get_job,
            append_stage_event=lambda *a, **kw: repository_threads.append(get_ident()),
            commit=lambda: None,
        )
        try:
            with pytest.raises((HTTPException, VerificationError)) as caught:
                if operation == "recheck":
                    await jobs.recheck_job_text(job_id, request, service, Settings())
                elif operation == "revision":
                    await jobs.create_review_revision(job_id, request, service, Settings())
                elif operation == "export":
                    await jobs.create_job_export(job_id, request, repository, service)
                else:
                    await anext(jobs._job_event_stream(job_id, 0, request))
            if isinstance(caught.value, HTTPException):
                assert caught.value.detail["code"] == "backend_unavailable"
            else:
                assert caught.value is failure
            assert threads and loop_thread not in threads
            assert all(thread == threads[0] for thread in repository_threads)
        finally:
            released.set()
            releaser.cancel()
            await asyncio.gather(releaser, return_exceptions=True)

    asyncio.run(exercise())
