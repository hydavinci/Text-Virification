from __future__ import annotations

import html
from typing import Any


def generate_report_html(data: dict[str, Any]) -> str:
    filename = html.escape(str(data.get("filename", "未知")))
    stats = _mapping(data.get("stats"))
    summary = _mapping(data.get("summary"))
    raw_issues = data.get("issues")
    issues: list[object] = raw_issues if isinstance(raw_issues, list) else []

    rows = "".join(_issue_row(index, _mapping(issue)) for index, issue in enumerate(issues, 1))
    if not rows:
        rows = (
            '<tr><td colspan="8" class="empty">'
            "未检测到明显问题"
            "</td></tr>"
        )
    type_chips = _chips(_mapping(summary.get("by_type")))
    severity_chips = _chips(_mapping(summary.get("by_severity")))

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>原文检查报告 - {filename}</title>
<style>
* {{ box-sizing: border-box; }}
body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
       margin: 0; padding: 30px; background: #f5f6fa; color: #333; }}
.container {{ max-width: 1100px; margin: auto; }}
.stats {{ display: flex; gap: 24px; flex-wrap: wrap; background: white;
          padding: 16px 24px; border-radius: 10px; }}
.stat strong {{ display: block; font-size: 20px; }}
.chips {{ display: flex; gap: 8px; flex-wrap: wrap; margin: 16px 0; }}
.chip, .badge {{ border-radius: 12px; padding: 3px 9px; background: #e2e8f0; }}
table {{ width: 100%; border-collapse: collapse; background: white; }}
th {{ background: #2c3e50; color: white; text-align: left; }}
th, td {{ padding: 10px; border-bottom: 1px solid #eee; vertical-align: top; }}
.original {{ color: #c0392b; font-weight: 600; }}
.suggestion {{ color: #17833d; font-weight: 600; }}
.empty {{ padding: 40px; text-align: center; color: #777; }}
</style>
</head>
<body><main class="container">
<h1>原文检查报告</h1><p>文件名：{filename}</p>
<section class="stats">
{_stat("总字符数", stats.get("char_count", 0))}
{_stat("不含空格字符数", stats.get("char_count_no_space", 0))}
{_stat("行数", stats.get("line_count", 0))}
{_stat("发现问题数", summary.get("total", 0))}
</section>
<div class="chips">{type_chips}</div><div class="chips">{severity_chips}</div>
<table><thead><tr>
<th>#</th><th>层级</th><th>类型</th><th>级别</th>
<th>原文</th><th>建议修改</th><th>说明</th><th>上下文</th>
</tr></thead><tbody>{rows}</tbody></table>
</main></body></html>"""


def _issue_row(index: int, issue: dict[str, Any]) -> str:
    values = [
        index,
        issue.get("layer", ""),
        issue.get("type", ""),
        issue.get("severity", ""),
        issue.get("original", ""),
        issue.get("suggestion") or "",
        issue.get("description", ""),
        issue.get("context", ""),
    ]
    escaped = [html.escape(str(value)) for value in values]
    return (
        f"<tr><td>{escaped[0]}</td><td><span class=\"badge\">{escaped[1]}</span></td>"
        f"<td>{escaped[2]}</td><td>{escaped[3]}</td>"
        f"<td class=\"original\">{escaped[4]}</td>"
        f"<td class=\"suggestion\">{escaped[5]}</td>"
        f"<td>{escaped[6]}</td><td>{escaped[7]}</td></tr>"
    )


def _chips(values: dict[str, Any]) -> str:
    return "".join(
        f'<span class="chip">{html.escape(str(name))}: {html.escape(str(count))}</span>'
        for name, count in values.items()
    )


def _stat(label: str, value: Any) -> str:
    return (
        f'<div class="stat"><strong>{html.escape(str(value))}</strong>'
        f"{html.escape(label)}</div>"
    )


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
