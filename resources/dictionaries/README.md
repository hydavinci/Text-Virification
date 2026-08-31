# 合规词库资源

词库的唯一运行时来源现已迁移到：

- `apps/api/src/text_verification/resources/dictionaries/sensitive_rules.json`
- `apps/api/src/text_verification/resources/dictionaries/ad_extreme_words.json`

修改词表时只更新以上包内文件；不要再维护额外的 JSON 副本。运行时版本号由词表源文
件字节的 SHA-256 摘要确定，因此任何内容变化都会反映到 `DictionarySnapshot.version`
和校验结果元数据中的 `dictionary_versions`。

修改后请至少运行后端的词库 / 兼容性相关测试，并确认打包产物中仍包含这两个 JSON。

词库内容由合规或法务团队维护。工程变更不得擅自扩充、删除或重新解释词条。
