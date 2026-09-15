from text_verification.scenarios.models import ScenarioProfile

PROFILE = ScenarioProfile(
    id="general",
    version="2",
    name="通用文档",
    description="检查基础文字质量，不要求论文、合同、新闻或技术文档的专用结构。",
    base_checks=(
        "punctuation", "brackets_quotes", "extra_spaces", "number_format",
        "chinese_typos", "variant_chars", "half_full_width", "missing_chars",
        "idiom_misuse", "term_consistency", "expression_issues", "grammar_patterns",
        "repeated_words", "english_spelling",
    ),
    extended_checks=("spacing", "extended_english", "long_sentences"),
    rules=(),
    semantic_guidance=(
        "通用文档：仅检查有明确上下文证据的语法、歧义和前后矛盾。"
        "保留日常口吻，不把口语当作错误；不要求摘要、合同当事人、新闻消息源或技术参数表。"
    ),
)
