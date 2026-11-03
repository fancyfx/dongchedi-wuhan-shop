# 本地车型配置与排名刷新

车型配置抓取、精确车型匹配、配置评分和排名计算 **不再由 GitHub Actions 执行**。后续统一在开发机本地完成，确认结果后再提交生成文件。

## 配置数据规则

1. 只使用新的完整 exact-trim 配置数据。
2. 旧 `exact-trims-1.json` ~ `exact-trims-4.json` 已废弃并删除。
3. 不兼容旧配置、不做 `series_year_tier` / `series_year` / 同车系高配继承。
4. 每次刷新前清空配置索引，从零重新匹配。
5. 只有 `trim_ah_*` 精确车型记录可以进入 `sku_to_trim`。
6. 未找到、歧义匹配、动力/变速箱/续航身份不一致时保持未核验，不给配置分。
7. 历史年份车型可以从 AutoHome `vaults` 历史参数快照读取；这里的“历史”仅指车型年份的数据源，不代表允许使用旧版配置 schema 或旧 shard。

## 一键本地刷新

在仓库根目录执行：

```bash
python3 scripts/local_refresh.py
```

脚本会：

- 在 `.external/` 准备/更新 `swoiow/autohome` 的 `main` 与 `vaults` 数据；
- 从空配置索引开始重新生成 exact-trim 配置；
- 重新计算 `data/listings-ranked.json`、`data/data-issues.json`、shortlist 和 dashboard 数据；
- 清理旧配置 metadata；
- 运行 AutoHome 匹配测试和排名回归测试；
- 构建 dashboard；
- 验证索引中不存在旧 trim ID / 旧 shard。

如果 AutoHome 数据已经准备好：

```bash
python3 scripts/local_refresh.py --skip-source-update
```

只想更新数据、不构建前端：

```bash
python3 scripts/local_refresh.py --skip-dashboard-build
```

## 看板「今日更新」

每日入库写完 `data/snapshots/YYYYMMDD/changelog.json` 和 `summary.json` 后，在仓库根目录执行：

```bash
python3 scripts/export_today_updates.py
```

脚本用 `dashboard/public/data/listings-ranked.json` 的 `rank`（全场 `total_score` 排名）对照 changelog，写出 `dashboard/public/data/today-updates.json`。重点推荐只包含 `change_type` 为 `added` 且排名在 1 到 10 的车。`updated` / `updated_price` 只算信息更新。

`python3 scripts/daily_ingest.py` 把快照写进 `data/snapshots/YYYYMMDD/` 时会顺带导出这份文件。`--snapshot-dir` 指到别的目录时不会导出，需要再跑上面的命令。排名文件更新之后也要再导出一次，否则重点推荐仍用上一次的名次。

演示「新入库且前 10」的标签：

```bash
python3 scripts/export_today_updates.py --write-fixture
```

看板打开「今日更新」，或访问 `?tab=today&today=fixture`。没有快照时用 `?tab=today&today=missing`，changelog 为空时用 `?tab=today&today=blank`。

## 提交要求

本地刷新成功后先检查：

```bash
git status
git diff --stat
git diff -- data/vehicle-specs-verified.json data/specs/exact-trim-sync-report.json data/meta.json
```

配置索引应满足：

```text
trim_files == ["specs/exact-trims-auto.json"]
所有 sku_to_trim 值均以 trim_ah_ 开头
```

然后将配置数据、排名结果、data-issues、meta 和 dashboard/public/data 作为同一批结果提交。

## GitHub Actions 边界

GitHub Actions 不允许再执行以下工作：

- 抓取车型配置；
- 拉取 AutoHome 参数库；
- exact-trim 匹配；
- 重算排名；
- 自动提交生成数据。

部署类 workflow 可以独立存在，但不得包含上述数据工作。
