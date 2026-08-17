from __future__ import annotations

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


async def handle_request_validation_error(
    request: Request,
    error: Exception,
) -> JSONResponse:
    if not isinstance(error, RequestValidationError):
        raise error
    code, message = _validation_error_detail(request, error)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": {"code": code, "message": message}},
    )


def _validation_error_detail(
    request: Request,
    error: RequestValidationError,
) -> tuple[str, str]:
    errors = error.errors()
    fields = {
        str(location[1])
        for item in errors
        if len(location := item.get("loc", ())) >= 2
    }

    if request.url.path.endswith("/issues") and fields & {
        "category",
        "severity",
        "decision",
        "search",
        "cursor",
        "limit",
    }:
        return (
            "invalid_issue_filters",
            "问题筛选条件无效，请刷新后重试。",
        )

    if request.url.path.endswith("/decisions") and "decisions" in fields:
        return "invalid_decision_request", "问题决策请求无效，请检查后重试。"

    if request.url.path.endswith("/jobs"):
        if "file" in fields:
            return "invalid_upload", "请选择要上传的文件。"
        if "scenario" in fields:
            return "invalid_check_scenario", "使用场景无效，请重新选择。"
        if "enabled_categories" in fields:
            has_blank_category = any(
                not str(item.get("input", "")).strip()
                for item in errors
                if "enabled_categories" in item.get("loc", ())
            )
            if has_blank_category:
                return "invalid_check_categories", "至少选择一个检查类别。"
            return "invalid_check_categories", "检查类别无效，请重新选择。"

    return "invalid_request", "请求参数无效，请检查后重试。"
