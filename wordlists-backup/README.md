# 合规词表备份（翻译预检系统）

本文件夹包含两套合规检查词表，供翻译预检系统（translation-pre-checker）使用。

## 文件说明
- `sensitive_rules.json` — 政治性/敏感词检查词典
  - `territory_standard`：领土/称谓规范表述（已预置港澳台规范：香港→中国香港、台湾→中国台湾、澳门→中国澳门）
  - `politics` / `ethnic_religion`：涉政、民族宗教红线词（当前留空，由合规/法务审定后补充）
- `ad_extreme_words.json` — 广告法极限词（绝对化用语）词表，面向营销材料检查

## 使用方法
将本文件夹内的两个 `.json` 文件复制到翻译预检系统项目的 `data/` 目录，覆盖同名文件即可生效：

    cp sensitive_rules.json ad_extreme_words.json <项目目录>/data/

## 生效方式
- 词表文件按修改时间（mtime）热加载，修改/替换后**无需重启**服务，下次检查即时生效。
- 若同时修改了 `analyzer.py`、`app.py` 等 Python 源码，则需要重启服务（本机为 launchctl 托管的 5088 端口服务）。

## 维护说明
词表内容由合规/法务团队审定维护，工程仅做引擎、不碰词表内容。新增条目后保存即生效。
