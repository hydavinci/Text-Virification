from importlib import import_module

from text_verification.domain.verification import Scenario
from text_verification.scenarios.models import ScenarioProfile

BASE_CHECK_NAMES = {
    "punctuation": "标点使用",
    "brackets_quotes": "括号与引号配对",
    "extra_spaces": "连续空格",
    "number_format": "数字、日期与编号格式",
    "chinese_typos": "中文常见错别字",
    "variant_chars": "异体字",
    "half_full_width": "全半角",
    "missing_chars": "疑似漏字",
    "idiom_misuse": "成语误用",
    "term_consistency": "术语一致性",
    "expression_issues": "表达搭配",
    "grammar_patterns": "明确语法模式",
    "repeated_words": "重复词语",
    "english_spelling": "英文常见拼写",
    "spacing": "中英文间距与空行",
    "extended_english": "扩展英文拼写与保守语法",
    "long_sentences": "长句人工审阅提示",
}


def get_profile(scenario: str) -> ScenarioProfile:
    try:
        selected = Scenario(scenario)
    except ValueError as error:
        raise ValueError(f"Unknown scenario: {scenario}") from error
    profile = import_module(f"text_verification.scenarios.{selected.value}").PROFILE
    if not isinstance(profile, ScenarioProfile) or profile.id != selected.value:
        raise ValueError(f"Invalid scenario package: {selected.value}")
    if any(
        name not in BASE_CHECK_NAMES for name in (*profile.base_checks, *profile.extended_checks)
    ):
        raise ValueError(f"Unknown baseline check in scenario package: {selected.value}")
    return profile


def scenario_catalog() -> list[dict[str, object]]:
    return [
        {
            "id": profile.id,
            "name": profile.name,
            "description": profile.description,
            "version": profile.version,
            "base_checks": [
                {"id": name, "name": BASE_CHECK_NAMES[name]} for name in profile.base_checks
            ],
            "extended_checks": [
                {"id": name, "name": BASE_CHECK_NAMES[name]} for name in profile.extended_checks
            ],
            "rules": [
                {
                    "id": rule.rule_id,
                    "name": rule.name,
                    "description": rule.description,
                    "requires_complete_structure": rule.requires_complete_structure,
                    "manual_only": True,
                }
                for rule in profile.rules
            ],
            "semantic_guidance": profile.semantic_guidance,
        }
        for profile in (get_profile(scenario.value) for scenario in Scenario)
    ]
