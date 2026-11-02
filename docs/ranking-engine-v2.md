# 懂车帝武汉二手车排名引擎 V2 设计说明

> 目标：用于 `fancyfx/dongchedi-wuhan-shop` 的二手车候选排序。  
> 当前用户偏好：**价格便宜优先、配置高、实际使用成本低、空间大、SUV 优先但不排斥轿车**。  
> 审计日期：2026-11-02  
> 配套核验数据：`vehicle-specs-verified.json`

---

## 1. 结论摘要

当前版本的加权计算本身基本没有算术错误，但排名结果存在结构性偏差，不能只通过“微调权重”解决。

当前公式：

```text
总分 = 配置 40% + 空间 25% + 油耗 15% + 价格 15% + SUV 5%
```

主要问题：

1. **PHEV 油耗口径错误**：把综合油耗（例如 1.x～2.x L/100km）与燃油车真实/官方油耗直接比较。
2. **真实油耗与官方油耗混用**：同一评分列中，有的车型是 WLTC/NEDC，有的是车主实耗，口径不一致。
3. **`specs_approx=true` / `series_year_tier` 会污染配置分**：相近档位的 AEB、ACC、360、座椅通风、电尾门等被误套给实际车型。
4. **里程 0% 权重**：9.25 万公里与 2 万公里的车几乎不受影响。
5. **车龄 0% 权重**：2020 年和 2025 年车型仅靠配置/空间比较，不符合二手车决策逻辑。
6. **分期展示价与现金价混排**：`price_type=分期` 的营销价格被当作可直接成交价格。
7. **价格权重过低**：用户明确优先低价，但当前只有 15%。
8. **min-max 依赖当前候选集合**：新增/删除极端车型会改变其他车辆得分，同一辆车的分数不稳定。
9. **缺失配置被近似补齐，而不是保留未知**：造成“数据越不准，分数反而越高”的风险。
10. **BEV/PHEV/ICE 的能源单位不可直接比较**：EV 的 kWh、PHEV 的油+电、ICE 的 L/100km 应统一到成本维度。
11. **车况没有成为门槛条件**：重大事故、水泡、火烧、三电异常等不应通过高配置分弥补。
12. **同车型不同车源没有充分拉开**：价格、里程、上牌年份未能正确体现二手车个体差异。

V2 建议改为固定锚点评分，不再基于候选集合 min-max。

```text
总分 =
    价格/购入成本     25%
  + 配置             20%
  + 实际使用成本     20%
  + 空间             15%
  + 车龄              5%
  + 里程              5%
  + 车身偏好          5%
  + 数据质量/风险      5%
```

> 注意：车况属于 **hard gate / 人工复核条件**，不是“多给几分少给几分”的普通维度。

---

# 2. 数据模型必须先重构

## 2.1 车源数据与车型参数分离

不要把懂车帝某条车源的价格、里程与车型公开参数混在同一个对象里作为“事实源”。建议拆分：

```json
{
  "listing": {
    "sku": "357301752",
    "title": "哈弗H6 2021款 第三代 2.0T 自动两驱Max版",
    "display_price_wan": 5.19,
    "price_type": "标价",
    "cash_price_wan": null,
    "finance_all_in_price_wan": null,
    "plate_date": null,
    "plate_year": 2021,
    "mileage_wan_km": 2.49
  },
  "model_specs": {
    "model_year": 2021,
    "trim": "第三代 2.0T 自动两驱Max版",
    "length_mm": 4653,
    "wheelbase_mm": 2738,
    "powertrain": "ice"
  },
  "verification": {
    "trim_match_level": "exact",
    "core_confidence": 0.99,
    "feature_confidence": 0.95
  }
}
```

### 原则

- `listing`：只描述“这一辆二手车”。
- `model_specs`：描述“这个具体年款/配置版本”。
- `verification`：描述“我们有多确定这些数据是真的”。

---

## 2.2 配置字段禁止用近似车型自动补齐

### 允许的匹配等级

```text
exact_trim              精确到年款 + 动力 + 配置名
same_powertrain_core    同年款同动力，仅允许继承不随配置变化的核心参数
series_year             同车系同年款，仅允许少量车身基础参数
series_only             只能用于辅助检索，不能用于配置打分
unknown                 不打配置分
```

### 最重要的规则

如果匹配结果不是 `exact_trim`：

**以下字段禁止自动填 `true`：**

```text
AEB
FCW
LDW/LKA/车道居中
BSD/DOW
ACC/IACC/全速自适应巡航
自动泊车/遥控泊车
360°全景影像
透明底盘
座椅加热
座椅通风
主/副驾驶电动座椅
HUD
无线充电
电动尾门
8155/高阶座舱芯片
L2 辅助驾驶
```

未找到精确证据时必须：

```json
"seat_ventilation": null
```

而不是：

```json
"seat_ventilation": false
```

更不能从同年高配车型填成：

```json
"seat_ventilation": true
```

### 为什么 `null` 很重要

- `false` = 已核实这台具体配置没有。
- `true` = 已核实这台具体配置有。
- `null` = 目前无法确认。

V1 最大的问题之一就是把“未知”变成了“高配车型大概有”。

---

# 3. 能源 / 油耗逻辑重构

## 3.1 禁止使用统一 `fuel_l_100km` 字段代表所有能源车型

建议字段：

```json
{
  "powertrain": "ice | phev | hev | bev",
  "fuel_grade": "92 | 95 | null",
  "official_fuel_l_100km": null,
  "official_standard": "WLTC | NEDC | CLTC | MIIT_combined",
  "low_soc_fuel_l_100km": null,
  "real_world_fuel_l_100km": null,
  "real_world_sample_n": null,
  "electric_kwh_100km": null,
  "ev_range_km": null,
  "ev_range_standard": null
}
```

---

## 3.2 ICE 燃油车

优先级：

```text
足量车主真实油耗（推荐 n >= 20）
    > 媒体标准化实测
    > 官方 WLTC
    > 官方 NEDC
```

排序输入：

```python
if real_world_sample_n >= 20:
    ranking_l100 = real_world_fuel_l_100km
    confidence = 1.0
elif media_test_available:
    ranking_l100 = media_test_l_100km
    confidence = 0.80
elif official_wltc_available:
    ranking_l100 = official_wltc_l100 * 1.15
    confidence = 0.65
elif official_nedc_available:
    ranking_l100 = official_nedc_l100 * 1.20
    confidence = 0.55
else:
    ranking_l100 = None
    confidence = 0.0
```

修正倍率必须配置化，不要写死在模型数据里。

---

## 3.3 PHEV 插混

### 严禁

把以下数据直接参与跨车型油耗排名：

```text
WLTC 综合油耗 1.36 L/100km
WLTC 综合油耗 1.74 L/100km
工信部综合油耗 1.8 L/100km
```

这些数字包含电能贡献，和普通燃油车 `8 L/100km` 不是同一口径。

### 默认场景：没有确认固定充电条件

使用：

```text
最低荷电状态（Low SOC / Charge Depleting 后）燃油消耗量
```

例如：

```text
宋Pro DM-i 71km：5.3 L/100km
海豹06 DM-i 80km：3.8 L/100km
秦PLUS DM-i 2025 55km：3.9 L/100km
秦PLUS DM-i 2024/2023：4.6 L/100km
```

老款 PHEV 如果没有可靠低 SOC 标准值：

- 使用有足够样本的车主实耗作为保守参考；
- 明确 `confidence`；
- 不允许拿综合 1.x L/100km 补位。

例如 2018 唐 DM：

```text
官方综合：1.8 L/100km   ❌ 不用于排名
车主众测：约 9.02 L/100km ✅ 可作为保守参考
```

---

## 3.4 有固定充电条件时的 PHEV 场景

以后可以增加用户参数：

```json
{
  "home_charging": true,
  "daily_km": 35,
  "electricity_price_yuan_kwh": 0.8,
  "gas_92_yuan_l": 8.0,
  "gas_95_yuan_l": 8.5
}
```

估算：

```python
energy_cost_100km = (
    ev_share * electric_kwh_100km * electricity_price
    + (1 - ev_share) * low_soc_l100 * gas_price
)
```

`ev_share` 不应该简单等于纯电续航/100，应由用户日均里程、充电频率和纯电实际可用续航估算。

---

## 3.5 BEV 纯电

使用：

```text
kWh/100km × 电价
```

不要为了兼容旧代码把它转换成“虚拟 L/100km”。

例如海鸥：

```text
9.6 kWh/100km
```

同时把续航/空间放在独立维度判断，不要因为能耗极低就自动成为最适合的大空间车型。

---

# 4. 所有动力统一为“每100公里能源成本”

核心比较指标建议改为：

```text
energy_cost_yuan_100km
```

示例：

```python
def energy_cost(vehicle, prices, scenario):
    if vehicle.powertrain == "ice":
        return vehicle.ranking_l100 * prices[vehicle.fuel_grade]

    if vehicle.powertrain == "phev" and scenario == "no_home_charging":
        return vehicle.low_soc_l100 * prices[vehicle.fuel_grade]

    if vehicle.powertrain == "bev":
        return vehicle.kwh100 * prices["electricity"]

    if vehicle.powertrain == "phev" and scenario == "home_charging":
        return (
            vehicle.ev_share * vehicle.kwh100 * prices["electricity"]
            + (1 - vehicle.ev_share) * vehicle.low_soc_l100 * prices[vehicle.fuel_grade]
        )
```

燃油价格/电价必须是配置项，例如：

```yaml
energy_prices:
  gas_92: 8.00
  gas_95: 8.50
  home_electricity: 0.80
  public_electricity: 1.50
```

不要把当前某天油价永久写进车型数据库。

---

# 5. 价格逻辑重构

## 5.1 不再直接拿 `display_price` 排名

字段：

```json
{
  "display_price_wan": 4.99,
  "price_type": "分期",
  "cash_price_wan": null,
  "finance_all_in_price_wan": null,
  "effective_price_wan": null,
  "price_confidence": 0.5,
  "needs_cash_quote": true
}
```

### 标价

如果明确为普通现金标价：

```python
effective_price = display_price
price_confidence = 0.9
```

### 分期价

如果只有营销分期价，没有贷款总成本：

```python
effective_price = display_price + FINANCE_UNCERTAINTY_RESERVE
price_confidence = 0.5
needs_cash_quote = True
```

建议默认：

```text
FINANCE_UNCERTAINTY_RESERVE = 0.5 万元
```

并允许配置 0.3～0.8 万元。

> 更理想：抓取/人工录入现金价、首付、贷款额、利率、期数、手续费，计算真实总支付成本。

---

## 5.2 价格评分使用固定锚点

当前 `(6 - price) / 6` 会导致价格维度太弱。

建议：

```python
def price_score(price_wan):
    # 当前筛选预算：<= 6万
    # 3万及以下视为价格维度满分，6万为0分
    return clamp((6.0 - price_wan) / 3.0 * 100, 0, 100)
```

示例：

| 可比价格 | 价格分 |
|---:|---:|
| 3.0万 | 100 |
| 3.5万 | 83.3 |
| 4.0万 | 66.7 |
| 4.5万 | 50.0 |
| 5.0万 | 33.3 |
| 5.5万 | 16.7 |
| 6.0万 | 0 |

优点：

- 不依赖候选集合；
- 每次重跑分数稳定；
- 1万元价差可以明显影响总排名；
- 符合“便宜优先”的用户需求。

---

# 6. 里程评分

建议固定锚点线性插值：

```text
0万  -> 100
1万  -> 100
2万  -> 95
3万  -> 90
4万  -> 82
5万  -> 72
6万  -> 62
8万  -> 42
10万 -> 20
>10万 -> 0 / 超出候选过滤条件
```

```python
MILEAGE_POINTS = [
    (0,100),(1,100),(2,95),(3,90),(4,82),
    (5,72),(6,62),(8,42),(10,20)
]
```

按点之间线性插值。

### 为什么必须加入

当前两台同款星瑞：

```text
5.39万 / 7.43万km
5.49万 / 9.25万km
```

后者价格更高、里程更多，V2 必须稳定排在前者之后。

---

# 7. 车龄评分

优先使用实际上牌年月：

```python
age_months = months_between(today, plate_date)
```

只有 `plate_year` 时，可用该年 7 月 1 日作为中性估计，并将车龄置信度降级。

锚点：

```text
<=2年 -> 100
3年   -> 90
4年   -> 80
5年   -> 68
6年   -> 55
8年   -> 30
10年  -> 10
>10年 -> 0 / 超出候选过滤条件
```

不要使用“车型年款”替代上牌时间。

---

# 8. 配置评分 V2

配置总权重从 40% 降至 20%，但内部更加重视真正有价值的配置。

## 8.1 不把动力性能放入配置分

删除 V1 中类似：

```text
powertrain_value
```

原因：

- 动力大不等于配置高；
- 大排量/四驱可能反而提高使用成本；
- 防止一项属性在多个维度重复加分。

---

## 8.2 推荐配置点数

### 安全 + 驾驶辅助：60 分

| 配置 | 分值 |
|---|---:|
| 6气囊及以上 | 8 |
| ESP | 3 |
| AEB | 10 |
| FCW | 4 |
| LKA | 5 |
| 车道居中 | 4 |
| BSD | 5 |
| DOW | 3 |
| ACC/全速ACC | 6 |
| 360°影像 | 6 |
| 前+后雷达 | 3 |
| 自动泊车 | 3 |

### 舒适配置：24 分

| 配置 | 分值 |
|---|---:|
| 主驾电动 | 2 |
| 副驾电动 | 2 |
| 座椅加热 | 3 |
| 座椅通风 | 5 |
| 全景天窗 | 2 |
| 电动尾门 | 3 |
| 无钥匙进入 | 1 |
| 远程启动 | 1 |
| 后排出风口 | 2 |
| 双区自动空调 | 2 |
| 皮质/仿皮座椅 | 1 |

### 座舱科技：20 分

| 配置 | 分值 |
|---|---:|
| 全液晶仪表 | 3 |
| >=12英寸中控 | 3 |
| CarPlay/HiCar/同类手机互联 | 2 |
| 无线充电 | 2 |
| 语音控制 | 2 |
| OTA | 2 |
| HUD | 3 |
| 8155级或同代高性能座舱芯片 | 3 |

总原始点最大约 104，最后标准化：

```python
config_raw = verified_points / 104 * 100
```

---

## 8.3 缺失配置必须做置信度收缩

假设某车型只有 60% 的配置权重得到精确核验：

```python
coverage = verified_weight / total_weight
config_score = 50 + coverage * (config_raw - 50)
```

意义：

- 数据缺失不会自动判成低配；
- 数据缺失也不会因为套用了同车系高配而变高分；
- 未知车型会向中性 50 分收缩。

`series_year_tier` 不允许把 feature coverage 当成已验证。

---

# 9. 空间评分

不要再用候选集合 min-max。

建议：

```text
空间 = 轴距45% + 宽度25% + 车长15% + 后备厢15%
```

如果后备厢数据缺失：

- 后备厢子项记 50；
- 同时降低空间数据置信度；
- 不要用车高代替后备厢空间。

### 固定锚点示例

#### 轴距

```text
2500 -> 20
2600 -> 40
2700 -> 65
2800 -> 90
2900 -> 100
```

#### 宽度

```text
1700 -> 20
1800 -> 55
1850 -> 75
1900 -> 90
1950 -> 100
```

#### 车长

```text
3800 -> 10
4300 -> 35
4600 -> 65
4800 -> 85
5000 -> 100
```

#### 后备厢

```text
300L -> 30
400L -> 55
500L -> 80
600L -> 100
```

均采用分段线性插值并 `clamp(0,100)`。

---

# 10. SUV / 车身偏好

因为用户“偏好 SUV，但不排斥轿车”，不要把轿车直接打 0。

建议：

```text
中型/紧凑型 SUV  -> 100
小型 SUV          -> 85
MPV               -> 90
旅行车            -> 75
掀背车            -> 55
轿车              -> 40
微型/小型两厢     -> 30
```

这一项只占 5%，避免车身形式压倒价格、成本、配置等更重要因素。

---

# 11. 使用成本评分

先得到：

```text
energy_cost_yuan_100km
```

然后使用固定锚点：

```text
<=15元 -> 100
20元   -> 95
30元   -> 85
40元   -> 70
50元   -> 55
60元   -> 40
70元   -> 25
80元   -> 10
>=90元 -> 0
```

优点：

- 92/95号汽油差异会自动体现；
- EV/PHEV/ICE 可以在同一个“钱”维度比较；
- 用户以后修改油价、电价，不需要重新改车型数据。

---

# 12. 数据质量 / 风险评分

建议 5% 权重。

### 基础质量

```text
精确trim + 权威参数 + 足量真实能耗数据     100
精确trim + 权威参数，真实能耗不足          90
核心参数精确、配置只部分核验               75
同动力核心参数匹配                         60
series_year_tier                           35
series_only                                20
无可靠来源                                  0
```

另外需要展示而不是隐藏：

```json
{
  "core_confidence": 0.99,
  "feature_confidence": 0.35,
  "energy_confidence": 0.95,
  "price_confidence": 0.5
}
```

---

# 13. 车况必须做 Hard Gate

以下条件不应该通过“高配置/低价格”抵消：

```text
重大事故 / 结构件受损
水泡
火烧
三电严重故障
里程无法核实
VIN / 维修记录异常
车辆性质为营运且未明确披露
非法改装
产权 / 抵押 / 查封风险
```

推荐状态：

```text
PASS
MANUAL_REVIEW
REJECT
```

示例：

```python
if flood or fire or structural_damage:
    return REJECT

if odometer_conflict or phev_battery_health_unknown:
    return MANUAL_REVIEW
```

对于 PHEV/BEV 二手车额外检查：

```text
SOH / 电池健康
快充次数（如可得）
三电质保是否随车/是否限首任
底盘电池包磕碰
故障码
营运历史
```

---

# 14. 异常里程提醒，不直接武断扣分

例如：

```text
接近6年但只有1.2万公里
```

可能是真的低里程，也可能需要核实。

计算：

```python
annual_mileage = mileage_km / max(age_years, 0.5)
```

建议标记：

```text
< 3000 km/year -> very_low_mileage_check
> 30000 km/year -> high_usage_check
```

只加风险提示，不直接判定调表。

---

# 15. 最终公式

```python
TOTAL = (
    price_score          * 0.25
    + config_score       * 0.20
    + operating_cost     * 0.20
    + space_score        * 0.15
    + age_score          * 0.05
    + mileage_score      * 0.05
    + body_preference    * 0.05
    + data_quality       * 0.05
)
```

如果 `condition_gate == REJECT`：

```python
ranking = None
```

如果 `condition_gate == MANUAL_REVIEW`：

保留分数，但 UI 显示：

```text
⚠️ 待人工确认，不应直接作为购买推荐
```

---

# 16. 不再使用全局 min-max

V1：

```python
normalized = (x - min(all_cars)) / (max(all_cars) - min(all_cars))
```

问题：

如果新增一辆极端油耗/尺寸车型，所有旧车的分数都会变化。

V2：每个维度采用固定锚点。

优点：

- 同一辆车今天和明天的分数可比较；
- 146辆变成500辆不会改变评分尺度；
- 测试容易写；
- 用户能够理解“为什么是这个分数”。

---

# 17. 分期价处理规则

这是必须修复的问题。

### UI 展示

建议同时展示：

```text
展示价：4.99万（分期营销价）
现金价：待确认
V2排序估算价：5.49万
价格置信度：低
```

默认保守规则：

```python
if price_type == "分期" and finance_all_in_price is None:
    effective_price = display_price + 0.5
    needs_cash_quote = True
else:
    effective_price = known_all_in_or_cash_price
```

不要让“分期直减 4000 元”的营销价格天然获得比现金标价更高的排名。

---

# 18. 必须加入回归测试

以下测试用例建议直接写进单测。

## Case 1：老唐 DM 油耗

```text
车型：2018 唐 DM 2.0T
```

断言：

```python
assert ranking_energy_l100 != 1.8
assert ranking_energy_l100 != 2.0
```

应该使用低SOC数据；若不存在，则使用明确标注的真实油耗参考，本次核验约 9.02L/100km。

---

## Case 2：同款星瑞个体差异

```text
A：5.39万 / 7.43万km
B：5.49万 / 9.25万km
```

其他车型参数完全相同。

断言：

```python
assert score(A) > score(B)
```

---

## Case 3：H6 低里程必须体现

```text
H6 Max：5.19万 / 2.49万km
```

不能再因为配置/油耗的单一 min-max 结果掉到第19而完全忽略低里程价值。

至少断言：

```python
assert mileage_score(2.49) > mileage_score(7.0)
```

---

## Case 4：近似配置不得生成高级功能

```python
match_level = "series_year_tier"
```

断言：

```python
assert features["seat_ventilation"] is None
assert features["aeb"] is None
assert features["camera_360"] is None
```

除非存在该具体 trim 的独立证据。

重点车型：

```text
博瑞 2021 1.8T领航版
捷达VS5 2022 自动悦享版Pro
逸动 2022 PLUS 1.6L 手动豪华型
轩逸 2022 经典1.6XL豪华版
海鸥 2024 305KM活力版
```

---

## Case 5：PHEV 统一低 SOC

```text
宋Pro DM-i：5.3L
海豹06 DM-i：3.8L
秦PLUS 2025：3.9L
秦PLUS 2024/2023：4.6L
```

断言：

```python
assert not use_combined_phev_fuel_for_cross_powertrain_ranking
```

---

## Case 6：95号汽油成本

星瑞、捷达 VS5 等要求 95 号油：

```python
cost_95 = fuel_l100 * price_95
cost_92 = fuel_l100 * price_92
assert cost_95 > cost_92
```

不要只比较 L/100km。

---

## Case 7：2024 缤越低里程

```text
2024 龙腾版：1.22万km
2023 铂金版：4.98万km
```

即使龙腾版价格稍高，里程与车龄必须能够贡献明确的分数差，而不是 0 权重。

---

# 19. API / 输出结构建议

最终每条排名结果建议输出：

```json
{
  "sku": "357301752",
  "score_v2": 76.4,
  "rank_v2": 3,
  "condition_gate": "MANUAL_REVIEW",
  "scores": {
    "price": 27.0,
    "config": 82.0,
    "operating_cost": 28.0,
    "space": 78.0,
    "age": 55.0,
    "mileage": 93.0,
    "body_preference": 100.0,
    "data_quality": 96.0
  },
  "confidence": {
    "price": 0.9,
    "config": 0.95,
    "energy": 1.0,
    "core_specs": 0.99
  },
  "reasons": [
    "2.49万公里，里程优势明显",
    "紧凑型SUV，空间符合偏好",
    "Max版配置较高",
    "真实油耗约9.2L/100km，使用成本偏高"
  ],
  "warnings": []
}
```

> 示例数字只表示结构，正式得分必须由程序按 V2 公式计算。

---

# 20. 推荐实现模块

```text
src/
  data/
    listing-normalizer.ts
    trim-matcher.ts
    spec-verifier.ts
    energy-normalizer.ts
  scoring/
    price-score.ts
    config-score.ts
    operating-cost-score.ts
    space-score.ts
    age-score.ts
    mileage-score.ts
    body-score.ts
    data-quality-score.ts
    total-score.ts
  risk/
    condition-gate.ts
    anomaly-flags.ts
  config/
    score-weights.ts
    score-anchors.ts
    energy-prices.ts
```

不要把所有逻辑继续堆在单个 `rerank_composite.py` 中。

---

# 21. 建议配置文件

```yaml
weights:
  price: 0.25
  config: 0.20
  operating_cost: 0.20
  space: 0.15
  age: 0.05
  mileage: 0.05
  body_preference: 0.05
  data_quality: 0.05

budget:
  hard_max_wan: 6.0
  full_price_score_wan: 3.0

finance:
  unknown_all_in_reserve_wan: 0.5

energy:
  default_scenario: no_home_charging
  gas_92_yuan_l: 8.0
  gas_95_yuan_l: 8.5
  home_electricity_yuan_kwh: 0.8
  public_electricity_yuan_kwh: 1.5
  wltc_fallback_multiplier: 1.15
  nedc_fallback_multiplier: 1.20

user_preference:
  suv_preferred: true
```

价格应由定时任务或配置更新，不要与车型参数耦合。

---

# 22. 数据来源优先级

车型基础参数：

```text
厂商官网
> 懂车帝 / 汽车之家 / 易车等精确车型参数页
> 主流参数数据库
> 其他可验证来源
```

真实油耗：

```text
足量车主统计数据
> 标准化媒体实测
> 官方WLTC
> NEDC
```

配置项：

```text
精确车型官方/主流参数页
> 精确车型第二来源交叉验证
> 其余全部视为未知
```

禁止：

```text
只通过“尊贵/旗舰/豪华”等名称猜配置
同车系高配向低配继承功能
把论坛单个车主油耗当作全车型平均值
```

---

# 23. 本次独立核验已经确认的典型错误

## 唐 DM 2018

- 独立核验尺寸约 `4870×1950×1725 / 2820mm`。
- 官方综合油耗约 `1.8L/100km`，不适合跨动力比较。
- 车主众测约 `9.02L/100km`，当前榜首油耗分明显被高估。

## 长安 UNI-T 2023 第二代旗舰

- WLTC 约 `6.45L/100km`。
- 车主众测约 `8.93L/100km`。
- 当前若直接使用 6.45，使用成本得分偏高。

## 宋 Pro DM-i 2024 71km

- 最低荷电状态 WLTC 约 `5.3L/100km`。
- 应使用 5.3，而不是综合 `2.87L/100km`。

## 锐程 PLUS 2023 尊贵

- 核心尺寸约 `4800×1825×1465 / 2770mm`。
- 真实油耗约 `8.19L/100km`。
- `series_year_tier` 近似配置不可继续参与配置加分。

## 博瑞 2021 1.8T领航

- 正确尺寸约 `4986×1861×1513 / 2870mm`。
- 真实油耗约 `8.85L/100km`。
- V1 中尺寸及高级驾驶辅助近似配置存在错误。

## 星瑞 2023 2.0T尊贵

- 真实油耗约 `8.30L/100km`。
- 使用 95 号汽油，成本计算必须体现油价差。

## 捷达 VS5 2022 悦享版Pro

- 核心尺寸约 `4418×1841×1616 / 2630mm`。
- 使用 95 号汽油。
- V1 的 360、L2、座椅通风、电尾门、无线充电等近似配置存在明显高估风险。

## VV7 2020 2.0T超豪

- 真实车主平均约 `10.86L/100km`。
- 对“低使用成本”用户应明显降低排名。

## H6 2021 三代2.0T两驱Max

- 尺寸约 `4653×1886×1730 / 2738mm`。
- 真实油耗约 `9.20L/100km`。
- 2.49万公里的低里程在 V1 完全没有被奖励，是当前排名偏低的重要原因。

## 秦 PLUS DM-i

- 2025 55km：低SOC约 `3.9L/100km`。
- 2024/2023：低SOC约 `4.6L/100km`。
- 综合 1.x～2.x L/100km 不得参与跨动力排名。

## 海鸥 2024 305km活力版

- `3780×1715×1540 / 2500mm`，4座。
- 能耗约 `9.6kWh/100km`。
- V1 高级配置近似匹配风险大；同时即便能源成本很低，也不能掩盖它与“空间大”需求冲突。

---

# 24. 开发迁移顺序

建议按以下顺序改，避免一次性重构难以验证：

### Phase 1：先修数据口径

1. 增加 `match_level` 强校验。
2. 禁止近似 trim 填高级配置。
3. 拆分 PHEV 综合油耗 / 低SOC / 实耗。
4. 加入 `fuel_grade`。
5. 分期价增加 `effective_price`。

### Phase 2：改评分

1. 删除 cohort min-max。
2. 加入固定锚点。
3. 加车龄、里程。
4. 改为能源成本。
5. 配置权重降至 20%。

### Phase 3：车况与置信度

1. 增加 hard gate。
2. 增加 `null` 配置语义。
3. 增加数据覆盖率和 confidence。
4. UI 展示风险和“为什么这个排名”。

### Phase 4：回归

至少运行第18节列出的 7 个固定回归用例后再更新线上榜单。

---

# 25. 本次 JSON 文件说明

`vehicle-specs-verified.json` 覆盖当前 `shortlist-ranked.json` 的 **全部前30条车源**。

每条包含：

- 原榜排名；
- SKU；
- 展示价 / 标价或分期；
- 上牌年份；
- 里程；
- 重新核验的动力类型；
- 车身尺寸 / 轴距 / 座位数；
- 发动机 / 变速箱；
- 燃油标号；
- 官方油耗口径；
- PHEV 最低荷电状态油耗；
- 真实油耗（有可靠样本时）；
- 电耗 / 续航（适用时）；
- 推荐的默认排名能源口径；
- 核验置信度；
- 数据来源 URL；
- 与当前仓库数据已发现的冲突/问题。

注意：

> JSON 中的 `feature_matrix.status=partial_or_exact_source_required` 是刻意设计的。没有逐项完成精确 trim 配置核验的车型，不应为了“数据完整”而再次猜出几十个 boolean。开发者应该保留 `null`，并由精确车型抓取任务逐步补齐。

---

# 26. 验收标准

V2 上线前至少满足：

- [ ] PHEV 不再用综合 1.x/2.x 油耗直接跨动力排名。
- [ ] BEV 不再伪装成 L/100km。
- [ ] 92/95 号汽油成本可区分。
- [ ] `series_year_tier` 不再自动产生高级配置 `true`。
- [ ] 车龄进入总分。
- [ ] 里程进入总分。
- [ ] 分期营销价有明确不确定性处理。
- [ ] 不再使用候选集合 min-max。
- [ ] 同款星瑞 5.39万/7.43万km 必须优于 5.49万/9.25万km。
- [ ] 数据缺失显示为 `null`，不是猜测值。
- [ ] 每个得分维度可输出解释。
- [ ] 重大事故/水泡/火烧进入 hard gate。
- [ ] 排名结果保存 `score_version`，支持 V1/V2 对比和回滚。

建议：

```json
"score_version": "v2.0.0"
```

并在榜单页面保留：

```text
算法版本 / 数据更新时间 / 能源场景 / 油价电价 / 价格置信度
```

这样未来排名变化可以追溯，而不是只看到一个无法解释的总分。
