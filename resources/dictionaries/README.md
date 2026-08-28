# 合规词库资源

本目录保存由合规或法务团队审定的中文检查资源：

- `advertising-extreme-terms.zh-cn.json`：广告法绝对化用语词表。
- `compliance-sensitive-rules.zh-cn.json`：敏感内容分类和规范表述替换规则。

当前交互式检查接口已加载与这些资源同步的包内词表，用于敏感表述和广告法极限词
检查。修改词表时应同步更新 `apps/api/src/text_verification/compatibility/data/` 中的
运行时副本，并通过测试确认规则变化。

词库内容由合规或法务团队维护。工程变更不得擅自扩充、删除或重新解释词条。
