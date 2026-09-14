"""Run a service-backed test gate without allowing missing services to pass as skips."""

import argparse
import os
import sys

import pytest


class NoSkippedTests:
    def __init__(self) -> None:
        self.skipped: list[str] = []

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.skipped:
            self.skipped.append(report.nodeid)

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.skipped:
            self.skipped.append(report.nodeid)

    def pytest_sessionfinish(self, session: pytest.Session) -> None:
        if self.skipped:
            print("\nCI gate rejected skipped tests:\n" + "\n".join(self.skipped), file=sys.stderr)
            session.exitstatus = pytest.ExitCode.TESTS_FAILED


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate", choices=("database", "live"), required=True)
    options, pytest_args = parser.parse_known_args()
    required = (
        ("TEST_DATABASE_URL",)
        if options.gate == "database"
        else ("LIVE_API_URL", "PREVIEW_RENDERER_TEST_URL", "LIVE_OCR_RUNTIME")
    )
    for name in required:
        if not os.environ.get(name):
            parser.error(f"{name} must be set for the {options.gate} gate")
    if options.gate == "live" and os.environ["LIVE_OCR_RUNTIME"] != "1":
        parser.error("LIVE_OCR_RUNTIME must be 1; real OCR cannot be skipped")
    return int(pytest.main(pytest_args, plugins=[NoSkippedTests()]))


if __name__ == "__main__":
    raise SystemExit(main())
