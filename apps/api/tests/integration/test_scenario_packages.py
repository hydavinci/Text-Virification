from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from text_verification.checkers.compatibility_checker import CompatibilityChecker
from text_verification.compatibility.adapters import text_to_document_model
from text_verification.compatibility.llm_review import _build_prompt
from text_verification.compatibility.semantic_discovery import _system_prompt
from text_verification.config import Settings, get_settings
from text_verification.domain.documents import FileType
from text_verification.domain.ports import CheckContext
from text_verification.domain.verification import Scenario
from text_verification.scenarios.registry import get_profile

SPECIALIST_CASES = (
    ("academic", "citation_reference", "😀文献[2]给出方法。\n参考文献\n[1] 张三，研究。", "[2]"),
    ("academic", "caption_reference", "😀见本文图2。\n图1：实验流程", "本文图2"),
    ("academic", "abbreviation_definition",
     "😀术语说明\n缩写 ABC：甲乙丙\n缩写 ABC：丁戊己", "丁戊己"),
    ("business", "line_item_total",
     "😀预算\n金额明细（完整）\n- 设计：10.10元\n- 开发：20.20元\n合计：31.00元", "31.00"),
    ("business", "date_order",
     "😀计划\n项目：迁移\n开始日期：2026-09-20\n结束日期：2026-09-10", "2026-09-10"),
    ("business", "action_clarity",
     "😀会议\n待办事项\n- 任务：提交报告；截止：尽快；负责人：张三", "尽快"),
    ("news", "headline_count",
     "标题：青山地震造成3人受伤\n导语：青山地震造成5人受伤。", "5"),
    ("news", "relative_date",
     "发布日期：2024年3月1日\n昨日（2024年2月28日）召开会议。", "昨日（2024年2月28日）"),
    ("news", "vague_source", "有数据显示，参与人数增长。", "有数据显示"),
    ("legal", "undefined_party",
     "采购合同\n甲方：星河公司\n第一条 交付\n乙方应依照本合同第3条付款。", "乙方"),
    ("legal", "missing_clause",
     "采购合同\n甲方：星河公司\n第一条 交付\n乙方应依照本合同第3条付款。", "本合同第3条"),
    ("legal", "amount_pair", "采购合同\n金额：1000元（大写：贰仟元整）", "贰仟"),
    ("technical", "version_range",
     "支持版本：1.2.0 - 2.0.0\n当前版本：2.1.0", "2.1.0"),
    ("technical", "missing_step",
     "操作步骤：\n步骤1：打开应用。\n步骤2：失败时返回步骤3。", "步骤3"),
    ("technical", "parameter_spelling",
     '参数定义：\nuser_id：用户编号😀\n示例：\n```json\n{"UserId": 1, "extra": 2}\n```', "UserId"),
)


@pytest.mark.parametrize(("scenario", "rule", "text", "original"), SPECIALIST_CASES)
@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["LF", "CRLF"])
def test_selected_package_reaches_the_real_api_with_manual_source_anchors(
    app: FastAPI, client: TestClient, scenario: str, rule: str, text: str, original: str,
    newline: str,
) -> None:
    text = text.replace("\n", newline)
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, llm_api_key="")
    response = client.post(
        "/api/v1/analyze", files={"text": (None, text)},
        data={"scenario": scenario, "enable_security": "false", "enable_sensitive": "false"},
    )
    assert response.status_code == 200
    assert response.json()["text"] == text
    issues = response.json()["issues"]
    matches = [issue for issue in issues if issue["rule_id"] == f"scenario.{scenario}.{rule}"]
    assert len(matches) == 1
    issue = matches[0]
    assert issue["original"] == original
    assert (issue["position"], issue["end_position"]) == (
        text.index(original), text.index(original) + len(original),
    )
    assert issue["suggestion"] is None and issue["auto_fixable"] is False
    assert issue["source"] == f"scenario.{scenario}"
    assert issue["rule_version"] == get_profile(scenario).version

    for other in Scenario:
        if other.value == scenario:
            continue
        document = text_to_document_model(text=text, source_name="input", file_type=FileType.TXT)
        result = CompatibilityChecker().check(
            document, CheckContext(scenario=other, enable_security=False, enable_sensitive=False),
        )
        assert not any(item.rule_id.startswith(f"scenario.{scenario}.") for item in result.issues)


def test_unselected_specialists_and_baseline_detectors_are_never_executed(monkeypatch) -> None:
    from text_verification.compatibility.analyzer import TextAnalyzer
    from text_verification.scenarios import academic

    def forbidden(*args, **kwargs):
        raise AssertionError("unselected detector was executed")

    monkeypatch.setattr(
        academic, "PROFILE",
        replace(academic.PROFILE, rules=tuple(
            replace(rule, check=forbidden) for rule in academic.PROFILE.rules
        )),
    )
    monkeypatch.setattr(TextAnalyzer, "_check_idiom_misuse", forbidden)
    document = text_to_document_model(
        text="支持版本：1.2.0 - 2.0.0\n当前版本：2.1.0",
        source_name="input", file_type=FileType.TXT,
    )
    result = CompatibilityChecker().check(
        document, CheckContext(scenario=Scenario.TECHNICAL, enable_sensitive=False),
    )
    assert any(issue.rule_id == "scenario.technical.version_range" for issue in result.issues)


@pytest.mark.parametrize("scenario", list(Scenario))
def test_custom_and_security_constraints_survive_every_package(scenario: Scenario) -> None:
    document = text_to_document_model(
        text="AI 禁止词 person@example.test", source_name="input", file_type=FileType.TXT,
    )
    result = CompatibilityChecker().check(document, CheckContext(
        scenario=scenario, enable_security=True, enable_sensitive=False,
        custom_glossary=({"original": "AI", "standard": "人工智能"},),
        banned_words=("禁止词",),
    ))
    assert {"custom_glossary", "banned_word", "pii_email"} <= {
        issue.rule_id for issue in result.issues
    }


def test_catalog_and_both_model_paths_use_the_actual_selected_package(client: TestClient) -> None:
    response = client.get("/api/v1/scenarios")
    assert response.status_code == 200
    catalog = response.json()["scenarios"]
    assert {item["id"] for item in catalog} == {scenario.value for scenario in Scenario}
    policies: set[str] = set()
    for item in catalog:
        profile = get_profile(item["id"])
        assert [rule["id"] for rule in item["rules"]] == [rule.rule_id for rule in profile.rules]
        assert all(rule["manual_only"] for rule in item["rules"])
        context = CheckContext(scenario=Scenario(profile.id))
        review, _ = _build_prompt([], context)
        discovery = _system_prompt(Settings(_env_file=None), context)
        assert profile.semantic_guidance in review
        assert profile.semantic_guidance in discovery
        assert "NOT a compliance" in discovery
        policies.add(profile.semantic_guidance)
    assert len(policies) == 6


def test_incomplete_file_extraction_keeps_local_evidence_but_not_absence_claims() -> None:
    document = text_to_document_model(
        text="项目：迁移\n开始日期：2026-09-20\n结束日期：2026-09-10",
        source_name="input.docx", file_type=FileType.DOCX,
    )
    result = CompatibilityChecker().check(document, CheckContext(
        scenario=Scenario.BUSINESS, enable_security=False, enable_sensitive=False,
    ))
    assert any(issue.rule_id == "scenario.business.date_order" for issue in result.issues)
    academic = text_to_document_model(
        text="文献[2]给出方法。\n参考文献\n[1] 张三，研究。",
        source_name="input.docx", file_type=FileType.DOCX,
    )
    result = CompatibilityChecker().check(academic, CheckContext(
        scenario=Scenario.ACADEMIC, enable_security=False, enable_sensitive=False,
    ))
    assert not any(
        issue.rule_id == "scenario.academic.citation_reference" for issue in result.issues
    )


def test_offline_evaluation_includes_specialists() -> None:
    from text_verification.domain.verification import VerificationOptions
    from text_verification.evaluation import ExpectedFinding, QualityCase, evaluate

    case = QualityCase(
        name="news-attribution", group="news", split="holdout",
        text="有数据显示，参与人数增长。",
        options=VerificationOptions(
            scenario=Scenario.NEWS, enable_security=False, enable_sensitive=False,
        ),
        expected=[ExpectedFinding(start=0, end=5, type="expression", suggestion=None)],
    )
    result = evaluate([case])
    assert result["overall"]["true_positives"] == 1
    assert result["overall"]["false_negatives"] == 0
    assert result["overall"]["false_positives"] == 0


def test_legacy_service_also_runs_selected_specialists() -> None:
    from text_verification.compatibility.service import analyze

    result = analyze(
        Settings(_env_file=None, llm_api_key=""), text="有数据显示，参与人数增长。",
        filename="input", file_id=None, file_extension=None, scenario=Scenario.NEWS,
        custom_glossary=[], banned_words=[], enable_security=False,
        enable_sensitive=False, enable_ad_extreme=False,
    )
    assert any(issue.rule_id == "scenario.news.vague_source" for issue in result.issues)


def test_rechecking_extracted_text_retains_its_incomplete_structure(
    app: FastAPI, client: TestClient,
) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, llm_api_key="")
    response = client.post("/api/v1/analyze", data={
        "text": "研究结果表明[2]。\n参考文献\n[1] 张三，研究。",
        "source_file_type": "docx", "scenario": "academic",
        "enable_security": "false", "enable_sensitive": "false",
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["file_type"] == "docx"
    assert not any(
        issue["rule_id"] == "scenario.academic.citation_reference"
        for issue in payload["issues"]
    )
    assert len(payload["degradation"]["reasons"]) == 2


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["LF", "CRLF"])
def test_applying_formatting_fixes_preserves_legal_clause_detection(
    app: FastAPI, client: TestClient, newline: str,
) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, llm_api_key="")
    text = newline.join([
        "采购合同", "甲方：星河公司", "第一条 总则", "甲方应依照本合同第3条付款。。",
    ])
    options = {"scenario": "legal", "enable_security": "false", "enable_sensitive": "false"}
    first = client.post("/api/v1/analyze", data={**options, "text": text})
    assert first.status_code == 200
    fixes = [
        issue for issue in first.json()["issues"]
        if issue["auto_fixable"] and issue["type"] in {"punctuation", "format"}
    ]
    assert fixes, "The regression must exercise an actual permitted formatting edit."
    for fix in sorted(fixes, key=lambda issue: issue["position"], reverse=True):
        text = text[:fix["position"]] + fix["suggestion"] + text[fix["end_position"]:]
    assert "第一条 总则" in text
    second = client.post("/api/v1/analyze", data={**options, "text": text})
    assert second.status_code == 200
    findings = [
        issue for issue in second.json()["issues"]
        if issue["rule_id"] == "scenario.legal.missing_clause"
    ]
    assert len(findings) == 1
    assert findings[0]["original"] == "本合同第3条"


@pytest.mark.parametrize("quoted", [
    "> 昨日（2024年2月28日）召开会议。",
    "“\n昨日（2024年2月28日）召开会议。\n”",
])
def test_news_quotations_do_not_inherit_the_republication_date(quoted: str) -> None:
    document = text_to_document_model(
        text=f"发布日期：2024年3月1日\n转载2月29日原文：\n{quoted}",
        source_name="input.md", file_type=FileType.MARKDOWN,
    )
    result = CompatibilityChecker().check(document, CheckContext(
        scenario=Scenario.NEWS, enable_security=False, enable_sensitive=False,
    ))
    assert not any(issue.rule_id == "scenario.news.relative_date" for issue in result.issues)


@pytest.mark.parametrize("example", [
    '{"extra":' + "[" * 12000 + "0" + "]" * 12000 + "}",
    '{"prefix\\"UserId": 1}',
])
def test_unsupported_json_examples_neither_abort_nor_invent_parameter_findings(
    app: FastAPI, client: TestClient, example: str,
) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, llm_api_key="")
    text = f"帐号\n参数定义：\nuser_id：用户编号\n示例：\n```json\n{example}\n```"
    response = client.post("/api/v1/analyze", data={
        "text": text, "scenario": "technical",
        "enable_security": "false", "enable_sensitive": "false",
    })
    assert response.status_code == 200
    rules = {issue["rule_id"] for issue in response.json()["issues"]}
    assert "scenario.technical.parameter_spelling" not in rules
    assert "cn_typo" in rules
