# mypy: ignore-errors
# ruff: noqa
"""
云端大模型语义复核模块（基于上下文理解降低误报）

设计原则：
1. 隐私优先：仅将"规则命中的局部上下文片段"发给大模型，绝不发送文档全文。
2. 安全降级：未配置 API key 时自动关闭；调用失败 / 解析失败时原样返回，绝不删除任何问题。
3. 仅复核低置信度项：error 级（错别字、异形字、禁用词、自定义术语）确定性较高，默认不送复核；
   只对 warning / info 级疑似问题做语义判断，避免漏掉真实硬错误。
4. 可插拔：遵循 OpenAI 兼容接口，支持任意兼容供应商（混元、通义、DeepSeek、OpenAI 等）。

环境变量：
  LLM_API_KEY      — 必填，供应商 API key（不配置则整个功能关闭）
  LLM_API_BASE     — 接口地址，默认 https://api.openai.com/v1
  LLM_MODEL        — 模型名，默认 gpt-4o-mini
  LLM_MAX_REVIEW   — 单次最多复核候选数，默认 40（超出的不予复核，避免成本过高）
  LLM_CONTEXT_RADIUS — 发给模型的上下文半径(字符)，默认 50
  LLM_TIMEOUT      — 请求超时(秒)，默认 60
  LLM_JSON_MODE    — 是否强制 json_object 返回格式，默认 0（0/1）
"""

import json
import logging
import re
from typing import List, Dict, Tuple, Any

from text_verification.config import Settings

logger = logging.getLogger(__name__)

try:
    from openai import (
        APIConnectionError,
        APIResponseValidationError,
        APIStatusError,
        APITimeoutError,
        OpenAI,
        RateLimitError,
    )
    PROVIDER_ERRORS = (APIConnectionError, APIStatusError)
    RETRYABLE_PROVIDER_ERRORS = (APIConnectionError, APITimeoutError, RateLimitError)
except ImportError:  # 未安装 SDK 时优雅降级
    OpenAI = None
    APIResponseValidationError = ()
    PROVIDER_ERRORS = ()
    RETRYABLE_PROVIDER_ERRORS = ()

# 仅复核这两类严重度的候选（error 级硬性错误直接保留，避免误删真实错别字）
REVIEW_SEVERITIES = {'warning', 'info'}
# 这些类型确定性高 / 属用户强约束，永远不送复核
NEVER_REVIEW_TYPES = {'banned_word', 'custom_term', 'typo', 'variant_char'}


class InvalidReviewResponseError(ValueError):
    pass


def is_llm_review_configured(settings: Settings) -> bool:
    """是否配置了云端复核。SDK/供应商故障由安全降级路径处理。"""
    return bool(settings.llm_api_key.strip())


def _excerpt(text: str, start: int, end: int, radius: int | None = None) -> str:
    """截取命中点前后的局部上下文（用于发给模型，不泄漏全文）"""
    resolved_radius = radius if radius is not None else 50
    a = max(0, start - resolved_radius)
    b = min(len(text), end + resolved_radius)
    pre = '…' if a > 0 else ''
    suf = '…' if b < len(text) else ''
    return f"{pre}{text[a:b]}{suf}"


def _build_prompt(candidates: List[Dict]) -> Tuple[str, str]:
    """构造单轮批量复核 prompt（system + user）"""
    blocks = []
    for c in candidates:
        blocks.append(
            f"[{c['index']}] 类型={c['type']} 严重度={c['severity']}\n"
            f"命中原文: {c['original']}\n"
            f"上下文: {c['context']}\n"
            f"规则说明: {c['description']}\n"
            f"规则建议: {c['suggestion']}"
        )
    body = "\n---\n".join(blocks)

    system = (
        "你是一位严谨的中文及中英双语审校专家。下面是一份文档经规则引擎初筛出的若干"
        "疑似问题。请结合每条给出的上下文，判断该问题是否是真正的错误。\n"
        "判定要点：\n"
        "1. 专有名词（人名、地名、机构名、品牌、产品名）、固定术语、行业惯用法不应判为错误；\n"
        "2. 合理的修辞、省略、以及数字格式/口语化等属正常写法的，应判为误报；\n"
        "3. 仅当结合上下文确有把握是错误时才判 real，否则优先 uncertain。\n"
        "请仅输出一个 JSON 数组，每个元素形如 "
        "{\"id\": 序号, \"verdict\": \"false_positive\"|\"real\"|\"uncertain\", "
        "\"reason\": \"简短理由，20字以内\"}。"
        "不要输出任何额外文字，不要使用 Markdown 代码块标记。"
    )
    user = (
        "待复核问题（已附上下文）：\n" + body +
        "\n\n请逐条给出 verdict。注意：仅在确有把握是误报时判 false_positive；"
        "无法确定时判 uncertain（系统会将其降级而非删除）。"
    )
    return system, user


def _parse_response(content: str, n_expected: int) -> Dict[int, Tuple[str, str]]:
    """解析模型返回的 JSON 数组，容错处理。返回 {序号: (verdict, reason)}"""
    if not content:
        raise InvalidReviewResponseError("LLM review response is empty.")
    content = content.strip()
    # 去掉可能的 ```json ... ``` 包裹
    if content.startswith('```'):
        content = re.sub(r'^```[a-zA-Z]*\n?', '', content)
        content = re.sub(r'\n?```$', '', content).strip()

    data = None
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        # 尝试提取第一个 [ ... ] 块
        m = re.search(r'\[.*\]', content, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                data = None

    if not isinstance(data, list):
        raise InvalidReviewResponseError("LLM review response is not a JSON array.")

    verdicts: Dict[int, Tuple[str, str]] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        idx = item.get('id')
        v = item.get('verdict')
        if idx is None or v not in ('false_positive', 'real', 'uncertain'):
            continue
        try:
            resolved_idx = int(idx)
        except (TypeError, ValueError) as error:
            raise InvalidReviewResponseError(
                "LLM review response contains an invalid issue index."
            ) from error
        if not 0 <= resolved_idx < n_expected:
            raise InvalidReviewResponseError(
                "LLM review response contains an out-of-range issue index."
            )
        verdicts[resolved_idx] = (v, str(item.get('reason', '')))
    return verdicts


def _response_content(response: Any) -> str:
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError) as error:
        raise InvalidReviewResponseError(
            "LLM review response does not contain message content."
        ) from error
    if not isinstance(content, str):
        raise InvalidReviewResponseError("LLM review response content is not text.")
    return content


def review_issues(settings: Settings, text: str, issues: List[Any]) -> Tuple[List[Any], Dict[str, Any]]:
    """
    对规则引擎产出的 issues 做云端语义复核。

    返回 (filtered_issues, review_stats)：
    - 未启用 / 调用失败 / 解析失败 → 原样返回 issues，绝不多删一条。
    - false_positive → 从结果中剔除（误报）。
    - uncertain      → 严重度降级为 info（存疑提示）。
    - real           → 保留。
    """
    stats = {
        'enabled': is_llm_review_configured(settings),
        'performed': False,
        'candidates': 0,
        'removed': 0,
        'downgraded': 0,
        'kept': 0,
        'failed': False,
        'failure_code': None,
        'retryable': False,
        'reason': '',
    }

    if not stats['enabled']:
        stats['reason'] = '未配置 LLM_API_KEY，已跳过云端复核'
        return issues, stats

    if OpenAI is None:
        stats['failed'] = True
        stats['failure_code'] = 'llm_client_unavailable'
        stats['reason'] = '大模型客户端不可用，已回退纯规则结果'
        logger.error("llm_review_client_unavailable")
        return issues, stats

    # 挑选送复核的候选（低严重度 + 非强约束类型）
    candidates = [
        (idx, issue) for idx, issue in enumerate(issues)
        if issue.severity in REVIEW_SEVERITIES
        and issue.type not in NEVER_REVIEW_TYPES
    ]
    stats['candidates'] = len(candidates)

    if not candidates:
        stats['reason'] = '无候选需复核（问题均为高确定性的硬性错误或自定义约束）'
        return issues, stats

    # 超过上限则只复核前 N 条，其余保留
    truncated = False
    if len(candidates) > settings.llm_max_review:
        candidates = candidates[:settings.llm_max_review]
        truncated = True

    payload = []
    for k, (orig_idx, issue) in enumerate(candidates):
        payload.append({
            'index': k,
            'type': issue.type,
            'severity': issue.severity,
            'original': issue.original,
            'context': _excerpt(text, issue.position, issue.end_position, settings.llm_context_radius),
            'description': issue.description,
            'suggestion': issue.suggestion,
        })

    client = OpenAI(
        api_key=settings.llm_api_key.strip(),
        base_url=settings.llm_api_base.strip(),
        timeout=settings.llm_timeout,
    )
    system, user = _build_prompt(payload)
    create_kwargs = {
        'model': settings.llm_model.strip(),
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user},
        ],
        'temperature': 0,
    }
    if settings.llm_json_mode:
        create_kwargs['response_format'] = {'type': 'json_object'}

    try:
        resp = client.chat.completions.create(**create_kwargs)
    except PROVIDER_ERRORS as error:
        logger.exception("llm_review_provider_failed")
        stats['failed'] = True
        stats['failure_code'] = 'llm_provider_error'
        stats['retryable'] = _is_retryable_provider_failure(error)
        stats['reason'] = '大模型调用失败，已回退纯规则结果'
        return issues, stats
    except APIResponseValidationError:
        stats['failed'] = True
        stats['failure_code'] = 'llm_invalid_response'
        stats['reason'] = '大模型返回无法解析，已回退纯规则结果'
        return issues, stats

    try:
        verdicts = _parse_response(_response_content(resp), len(payload))
    except InvalidReviewResponseError:
        stats['failed'] = True
        stats['failure_code'] = 'llm_invalid_response'
        stats['reason'] = '大模型返回无法解析，已回退纯规则结果'
        return issues, stats

    stats['performed'] = True

    # 应用判定
    removed_idx = set()
    for k, (orig_idx, issue) in enumerate(candidates):
        v = verdicts.get(k)
        if v is None:
            issue.review = 'no_verdict'
            issue.review_reason = ''
            stats['kept'] += 1
            continue
        verdict, reason = v
        issue.review = verdict
        issue.review_reason = reason
        if verdict == 'false_positive':
            removed_idx.add(orig_idx)
            stats['removed'] += 1
        elif verdict == 'uncertain':
            issue.severity = 'info'  # 降级为提示，不删除
            if issue.description and '（经语义复核仍存疑' not in issue.description:
                issue.description = issue.description + '（经语义复核仍存疑，已降级为提示）'
            stats['downgraded'] += 1
        else:  # real
            stats['kept'] += 1

    if truncated:
        stats['reason'] = f'候选数超上限，仅复核前 {settings.llm_max_review} 条'

    # 重建结果：剔除被判定为误报的项
    final = [issue for idx, issue in enumerate(issues) if idx not in removed_idx]
    return final, stats


def _is_retryable_provider_failure(error: Exception) -> bool:
    if isinstance(error, (TimeoutError, ConnectionError, *RETRYABLE_PROVIDER_ERRORS)):
        return True
    status_code = getattr(error, "status_code", None)
    return isinstance(status_code, int) and (
        status_code in {408, 409, 425, 429} or status_code >= 500
    )
