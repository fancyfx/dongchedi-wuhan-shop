# 懂车帝汽车商城·武汉店 二手车抓取

- 店铺：懂车帝汽车商城·武汉店（shop_id=118608）
- 硬条件：价格 ≤6 万；里程 ≤10 万公里；车龄 ≤10 年（上牌年 ≥ 当年-10）
- 另排除短续航纯电：续航 ≤300km 的纯电，或无法解析续航的微型/城市代步纯电（宏光 MINIEV、Lumin、熊猫、之光 EV、Air ev 等）；插混/增程与续航 >300 纯电保留。入库脚本见 `scripts/filters.py`（`is_short_range_bev` / `keep_listing`），命中则不入库。
- 排序：综合总得分（配置 35% + 空间 25% + 油耗 20% + 价格 15% + SUV 5%），见 `scripts/rerank_composite.py`
- 数据：`data/` 快照；`images/` 封面短图；看板 `dashboard/`
- 今日更新：入库后 `python3 scripts/export_today_updates.py` 生成 `dashboard/public/data/today-updates.json`（重点推荐 = 新入库且全场排名 ≤ 10）。说明见 `docs/local-data-refresh.md`
- 说明：H5 须微信 UA；页面「共 N 辆」可能含外店，入库以本店 sku 为准

公开仓，供比价与晨检监控；看板 https://dongchedi-wuhan-dashboard.vercel.app 。

## 评分（2026-11-02）

- 综合分：配置40% + 空间25% + 油耗15% + 价格15% + SUV5%
- 配置分来自公开真实参配特征（非标题档位词）
- 口碑含独立「缺点」专节（cons）
- 排除短续航纯电（≤300km / 微型代步）
