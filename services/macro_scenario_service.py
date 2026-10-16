# -*- coding: utf-8 -*-
"""宏观趋势与情景推演服务。

这个模块把现有官方/缓存 observation 转成可复核的条件情景，而不是把结果
命名为官方预测。它提供三件事：

* 使用历史连续尾段的变化分布生成上行、基准、下行路径；
* 对近期变化残差做固定种子移动块重抽样，给出 P10/P50/P90 敏感性区间；
* 用滚动起点回测同一套规则，报告 MAE、RMSE、方向命中和区间覆盖。

模型刻意保持透明：不使用未来数据，不做因果识别，不把缺失值插成观测，
也不把情景结果写回原始数据库。不同指标的“上行/下行”只表示数值路径
较高/较低；它不自动等价于整体经济变好/变坏。
"""

import math
import random
import re
import sqlite3
from contextlib import closing
from datetime import datetime


SCENARIO_KEYS = ("upper", "base", "lower")
SCENARIO_LABELS = {"upper": "上行", "base": "基准", "lower": "下行"}
DEFAULT_INDICATOR = "CN_GDP_Q_REAL_YOY"
DEFAULT_HORIZON = 12
DEFAULT_SIMULATIONS = 1000
MIN_SIMULATIONS = 100
MAX_SIMULATIONS = 3000
MAX_HORIZON = 40


# 这里的目录只声明现有 observation 的入口；缺指标不会被用别的指标代填。
# mode=rate 使用百分点变化，mode=level 使用对数变化。
SERIES_CATALOG = (
    {
        "code": "CN_GDP_Q_REAL_YOY", "name": "GDP实际增速", "category": "增长",
        "table": "china_macro_observations", "frequency": "quarterly", "mode": "rate",
        "unit": "%", "interpretation": "数值上行代表实际增长率更高。",
    },
    {
        "code": "CN_IP_YOY", "name": "工业增加值当月同比", "category": "生产",
        "table": "china_macro_observations", "frequency": "monthly", "mode": "rate",
        "unit": "%", "calendar_bridge_month": 2,
        "interpretation": "数值上行代表工业同比增速更高；1—2月合并发布记为2月。",
    },
    {
        "code": "CN_RETAIL_YOY", "name": "社会消费品零售当月同比", "category": "需求",
        "table": "china_macro_observations", "frequency": "monthly", "mode": "rate",
        "unit": "%", "calendar_bridge_month": 3,
        "interpretation": "数值上行代表消费同比增速更高；当前来源将年初合并值记在3月。",
    },
    {
        "code": "CN_FAI_YTD_YOY", "name": "固定资产投资累计同比", "category": "需求",
        "table": "china_macro_observations", "frequency": "monthly", "mode": "rate",
        "unit": "%", "calendar_bridge_month": 2,
        "interpretation": "累计同比口径，不等于单月投资流量；1—2月合并发布记为2月。",
    },
    {
        "code": "CN_CPI_YOY", "name": "CPI同比", "category": "价格",
        "table": "china_macro_observations", "frequency": "monthly", "mode": "rate",
        "unit": "%", "interpretation": "上行代表消费价格同比更高，不自动代表经济更好。",
    },
    {
        "code": "CN_PPI_YOY", "name": "PPI同比", "category": "价格",
        "table": "china_macro_observations", "frequency": "monthly", "mode": "rate",
        "unit": "%", "interpretation": "上行代表工业出厂价格同比更高。",
    },
    {
        "code": "CN_UNEMP_SURVEY", "name": "城镇调查失业率", "category": "就业",
        "table": "china_macro_observations", "frequency": "monthly", "mode": "rate",
        "unit": "%", "interpretation": "数值上行通常表示失业率压力更高。",
    },
    {
        "code": "CN_EXPORT_YOY", "name": "出口当月同比", "category": "外贸",
        "table": "china_macro_observations", "frequency": "monthly", "mode": "rate",
        "unit": "%", "interpretation": "数值上行代表出口同比增速更高。",
    },
    {
        "code": "CN_IMPORT_YOY", "name": "进口当月同比", "category": "外贸",
        "table": "china_macro_observations", "frequency": "monthly", "mode": "rate",
        "unit": "%", "interpretation": "数值上行代表进口同比增速更高。",
    },
    {
        "code": "CN_FAI_MANUFACTURING_YTD_YOY", "name": "制造业投资累计同比", "category": "生产",
        "table": "china_macro_observations", "frequency": "monthly", "mode": "rate",
        "unit": "%", "calendar_bridge_month": 2,
        "interpretation": "制造业投资累计同比，不等于产能利用率；1—2月合并发布记为2月。",
    },
    {
        "code": "M2y", "name": "M2同比", "category": "货币",
        "table": "monthly_data", "column": "M2y", "frequency": "monthly", "mode": "rate",
        "unit": "%", "interpretation": "数值上行代表广义货币同比增速更高。",
    },
    {
        "code": "M1y", "name": "M1同比", "category": "货币",
        "table": "monthly_data", "column": "M1y", "frequency": "monthly", "mode": "rate",
        "unit": "%", "interpretation": "数值上行代表M1同比增速更高。",
    },
    {
        "code": "loany", "name": "人民币贷款余额同比", "category": "信用",
        "table": "monthly_data", "column": "loany", "frequency": "monthly", "mode": "rate",
        "unit": "%", "interpretation": "数值上行代表贷款余额同比增速更高。",
    },
    {
        "code": "SFy", "name": "社融存量同比", "category": "信用",
        "table": "monthly_data", "column": "SFy", "frequency": "monthly", "mode": "rate",
        "unit": "%", "interpretation": "数值上行代表社融存量同比增速更高。",
    },
    {
        "code": "LPR_5Y", "name": "5年期LPR", "category": "利率",
        "table": "china_rates_observations", "frequency": "monthly", "mode": "rate",
        "unit": "%", "interpretation": "数值上行代表按揭/长期贷款政策报价更高。",
    },
    {
        "code": "sales_area_ytd_yoy_official", "name": "商品房销售面积累计同比", "category": "房地产",
        "table": "housing_national_observations", "frequency": "monthly", "mode": "rate",
        "unit": "%", "calendar_bridge_month": 2,
        "interpretation": "累计销售面积同比，不等于单月成交面积；1—2月合并发布记为2月。",
    },
    {
        "code": "QCNR628BIS", "name": "中国实际房价指数", "category": "房地产",
        "table": "housing_national_observations", "frequency": "quarterly", "mode": "level",
        "unit": "index", "interpretation": "数值上行代表BIS实际房价指数更高。",
    },
    {
        "code": "CN_IND_PROFIT_YTD_YOY", "name": "工业利润累计同比（官方）", "category": "企业经营",
        "table": "china_macro_observations", "frequency": "monthly", "mode": "rate",
        "unit": "%", "calendar_bridge_month": 2,
        "interpretation": "官方可比口径累计同比；不是单月利润、现金流或企业因果模型。",
    },
    {
        "code": "CN_CAPACITY_UTILIZATION", "name": "工业产能利用率", "category": "企业经营",
        "table": "china_macro_observations", "frequency": "quarterly", "mode": "rate",
        "unit": "%", "interpretation": "官方产能利用率；不以工业产量增长替代。",
    },
)


# 这是“当前系统缺口清单”，不是用来补数据的 mock。页面用它告诉使用者下一步
# 哪些内容最值得接入，避免系统只展示已经有的指标而隐藏研究问题。
GAP_CATALOG = (
    {
        "code": "CN_INDUSTRIAL_PROFIT", "label": "规模以上工业企业利润",
        "priority": "P0", "status": "not_in_current_catalog",
        "reason": "稿件高频讨论工业利润、产能过剩和顺差，但当前中国宏观指标目录没有利润月度序列。",
        "next_step": "接入国家统计局工业企业利润月报，保留累计/当月推导边界。",
    },
    {
        "code": "CN_CAPACITY_UTILIZATION", "label": "工业产能利用率",
        "priority": "P0", "status": "not_in_current_catalog",
        "reason": "工业增加值不能替代产能利用率，无法单独回答产能过剩问题。",
        "next_step": "接入季度产能利用率及行业分项，禁止用产量同比替代。",
    },
    {
        "code": "CN_MIGRANT_WORKER_SURVEY", "label": "农民工专项调查",
        "priority": "P1", "status": "not_in_current_catalog",
        "reason": "当前有就业人员和城镇调查失业率，但没有农民工规模、工资和流动专项序列。",
        "next_step": "接入国家统计局农民工监测调查年度/季度公开表。",
    },
    {
        "code": "CN_YOUTH_GRADUATE_LABOR", "label": "青年与高校毕业生就业",
        "priority": "P1", "status": "not_in_current_catalog",
        "reason": "官方总失业率无法替代青年就业、毕业生就业和就业质量。",
        "next_step": "建立年龄/身份分组并保留发布口径变化，不构造‘真实失业率’单值。",
    },
    {
        "code": "CN_BANK_NIM_NPL", "label": "银行净息差与不良贷款",
        "priority": "P1", "status": "not_in_current_catalog",
        "reason": "稿件把LPR、息差、坏账和信用收缩联系在一起，当前系统只有利率和贷款总量。",
        "next_step": "接入银行业监管统计或上市银行财报，区分官方总表和公司样本。",
    },
    {
        "code": "CN_TRADE_PARTNER_PRODUCT", "label": "国别/产品贸易与制裁事件",
        "priority": "P1", "status": "not_in_current_catalog",
        "reason": "当前外贸主要是总额和增速，不能复现中俄、越南、关税和双用途商品叙事。",
        "next_step": "接入海关国别/HS产品维度，并单独建设政策与制裁事件表。",
    },
    {
        "code": "CN_POLICY_EVENT_TIMELINE", "label": "政策、企业与财政事件时间线",
        "priority": "P1", "status": "not_in_current_catalog",
        "reason": "万科、恒大、反内卷、化债、社保和医保基金属于事件/文本，不是数值序列。",
        "next_step": "建立事件来源、发布日期、适用范围、状态和证据链接，不把评论写成观测。",
    },
    {
        "code": "CN_MORTALITY_HEALTH_DETAIL", "label": "年龄别死亡与健康支出",
        "priority": "P2", "status": "not_in_current_catalog",
        "reason": "人口总死亡数无法支持实际死亡年龄、死因或健康冲击的推演。",
        "next_step": "先接入年龄别死亡/死因/卫生支出，再考虑敏感性情景。",
    },
)


def _period_key(period, frequency):
    text = str(period or "")
    if frequency == "monthly":
        match = re.match(r"^(\d{4})-(\d{2})", text)
        return int(match.group(1)) * 12 + int(match.group(2)) - 1 if match else None
    if frequency == "quarterly":
        match = re.match(r"^(\d{4})-Q([1-4])", text)
        if match:
            return int(match.group(1)) * 4 + int(match.group(2)) - 1
        match = re.match(r"^(\d{4})-(\d{2})", text)
        if match:
            return int(match.group(1)) * 4 + (int(match.group(2)) - 1) // 3
        return None
    match = re.match(r"^(\d{4})", text)
    return int(match.group(1)) if match else None


def _next_period(period, frequency):
    text = str(period)
    if frequency == "monthly":
        match = re.match(r"^(\d{4})-(\d{2})", text)
        if not match:
            return None
        year, month = int(match.group(1)), int(match.group(2))
        month += 1
        if month == 13:
            year, month = year + 1, 1
        return f"{year:04d}-{month:02d}"
    if frequency == "quarterly":
        match = re.match(r"^(\d{4})-Q([1-4])", text)
        quarter_style = bool(match)
        if not match:
            key = _period_key(text, frequency)
            if key is None:
                return None
            year, quarter = divmod(key, 4)
        else:
            year, quarter = int(match.group(1)), int(match.group(2)) - 1
        quarter += 1
        if quarter == 4:
            year, quarter = year + 1, 0
        return (f"{year:04d}-Q{quarter + 1}" if quarter_style
                else f"{year:04d}-{(quarter + 1) * 3:02d}")
    match = re.match(r"^(\d{4})", text)
    return f"{int(match.group(1)) + 1:04d}" if match else None


def _sort_rows(rows, frequency):
    by_period = {}
    for row in rows:
        period = str(row.get("period") or "")
        try:
            value = float(row.get("value"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value) or _period_key(period, frequency) is None:
            continue
        item = dict(row)
        item["period"] = period[:7] if frequency == "monthly" else period
        item["value"] = value
        by_period[item["period"]] = item
    return [by_period[key] for key in sorted(by_period,
                                             key=lambda p: _period_key(p, frequency))]


def _latest_contiguous_tail(rows, frequency, calendar_bridge_month=None):
    if not rows:
        return []
    start = 0
    for index in range(1, len(rows)):
        previous = _period_key(rows[index - 1]["period"], frequency)
        current = _period_key(rows[index]["period"], frequency)
        bridge = False
        if (frequency == "monthly" and calendar_bridge_month is not None
                and previous is not None and current is not None):
            previous_month = (previous % 12) + 1
            current_month = (current % 12) + 1
            bridge = (previous_month == 12 and
                      current_month == int(calendar_bridge_month))
        if previous is None or (current != previous + 1 and not bridge):
            start = index
    return rows[start:]


def _quantile(values, probability):
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * probability
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[int(lower)]
    weight = position - lower
    return ordered[int(lower)] * (1.0 - weight) + ordered[int(upper)] * weight


def _periods_per_year(frequency):
    return {"monthly": 12, "quarterly": 4, "annual": 1}.get(frequency, 12)


def _minimum_history(frequency):
    return {"monthly": 18, "quarterly": 8, "annual": 6}.get(frequency, 18)


def _changes(rows, mode):
    values = [float(row["value"]) for row in rows]
    if mode == "level":
        out = []
        for previous, current in zip(values, values[1:]):
            if previous <= 0 or current <= 0:
                continue
            out.append(math.log(current / previous))
        return out
    return [current - previous for previous, current in zip(values, values[1:])]


def _apply_change(value, change, mode):
    if mode == "level":
        return value * math.exp(change)
    return value + change


def _scenario_paths(rows, frequency, mode, horizon):
    changes = _changes(rows, mode)
    if len(changes) < 4:
        return None
    recent = changes[-min(len(changes), 36):]
    drifts = {
        "upper": _quantile(recent, 0.75),
        "base": _quantile(recent, 0.50),
        "lower": _quantile(recent, 0.25),
    }
    latest = rows[-1]
    periods_year = _periods_per_year(frequency)
    paths = []
    for key in SCENARIO_KEYS:
        value = float(latest["value"])
        path = []
        for step in range(1, horizon + 1):
            # 逐步衰减，避免把短期冲击机械地直线外推多年。
            change = float(drifts[key]) * (0.96 ** (step - 1))
            value = _apply_change(value, change, mode)
            path.append({
                "period": _next_period(latest["period"], frequency)
                if step == 1 else _next_period(path[-1]["period"], frequency),
                "value": round(value, 6),
            })
        drift = float(drifts[key])
        annualised = ((math.exp(drift) - 1.0) * periods_year * 100.0
                      if mode == "level" else drift * periods_year)
        paths.append({
            "key": key,
            "label": SCENARIO_LABELS[key],
            "drift_per_period": round(drift, 8),
            "annualised_drift": round(annualised, 4),
            "path": path,
            "end_value": path[-1]["value"],
        })
    return paths


def _simulate(rows, frequency, mode, horizon, simulations, seed):
    changes = _changes(rows, mode)
    if len(changes) < 12:
        return {
            "status": "insufficient_history", "data_status": "scenario",
            "reason": "近期变化不足12个观测，未运行扰动模拟。",
        }
    recent = changes[-min(len(changes), 60):]
    base_drift = _quantile(recent, 0.50)
    residuals = [value - base_drift for value in recent]
    if len(residuals) < 8:
        return {
            "status": "insufficient_history", "data_status": "scenario",
            "reason": "近期残差不足8个观测，未运行扰动模拟。",
        }
    simulations = max(MIN_SIMULATIONS, min(MAX_SIMULATIONS, int(simulations)))
    rng = random.Random(int(seed))
    block_size = min(3 if frequency == "monthly" else 2, len(residuals))
    values = [[] for _ in range(horizon)]
    latest_value = float(rows[-1]["value"])
    max_start = max(0, len(residuals) - block_size)
    for _ in range(simulations):
        shocks = []
        while len(shocks) < horizon:
            start = rng.randint(0, max_start) if max_start else 0
            shocks.extend(residuals[start:start + block_size])
        value = latest_value
        period = rows[-1]["period"]
        for step in range(horizon):
            change = float(base_drift) * (0.96 ** step) + shocks[step]
            value = _apply_change(value, change, mode)
            period = _next_period(period, frequency)
            values[step].append(value)
    points = []
    period = rows[-1]["period"]
    for point in values:
        period = _next_period(period, frequency)
        points.append({
            "period": period,
            "p10": round(_quantile(point, 0.10), 6),
            "p50": round(_quantile(point, 0.50), 6),
            "p90": round(_quantile(point, 0.90), 6),
        })
    return {
        "status": "ok", "data_status": "scenario", "simulations": simulations,
        "seed": int(seed), "block_size": block_size, "points": points,
        "end": points[-1] if points else None,
        "method": "近期变化残差的固定种子移动块重抽样；P10/P50/P90是敏感性区间，不是概率或置信区间。",
    }


def _forecast_values(rows, frequency, mode, horizon):
    paths = _scenario_paths(rows, frequency, mode, horizon)
    return {item["key"]: item["path"] for item in paths} if paths else {}


def _backtest(rows, frequency, mode, horizon):
    minimum = _minimum_history(frequency)
    if len(rows) < minimum + max(3, horizon) + 1:
        return {
            "status": "insufficient_sample", "data_status": "derived",
            "reason": f"历史观测不足，至少需要{minimum + max(3, horizon) + 1}个连续点。",
        }
    errors, squared, directions, covered = [], [], [], []
    origins = []
    origin_count = 0
    # 只用过去数据拟合，在滚动起点上验证未来；步长按频率控制计算量。
    step_size = 1 if frequency == "monthly" else 1
    for origin in range(minimum, len(rows) - horizon + 1, step_size):
        train = rows[:origin]
        paths = _scenario_paths(train, frequency, mode, horizon)
        if not paths:
            continue
        by_key = {item["key"]: item for item in paths}
        actual = rows[origin:origin + horizon]
        origin_count += 1
        base_path = by_key["base"]["path"][:len(actual)]
        upper_path = by_key["upper"]["path"][:len(actual)]
        lower_path = by_key["lower"]["path"][:len(actual)]
        previous = float(train[-1]["value"])
        for actual_row, base_row, upper_row, lower_row in zip(
                actual, base_path, upper_path, lower_path):
            actual_value = float(actual_row["value"])
            forecast_value = float(base_row["value"])
            error = forecast_value - actual_value
            errors.append(abs(error))
            squared.append(error * error)
            actual_delta = actual_value - previous
            forecast_delta = forecast_value - previous
            if actual_delta != 0 and forecast_delta != 0:
                directions.append((actual_delta > 0) == (forecast_delta > 0))
            low = min(float(lower_row["value"]), float(upper_row["value"]))
            high = max(float(lower_row["value"]), float(upper_row["value"]))
            covered.append(low <= actual_value <= high)
            previous = actual_value
        if len(origins) < 12:
            origins.append({
                "as_of": train[-1]["period"],
                "target_period": actual[-1]["period"],
                "base_end": base_path[-1]["value"],
                "actual_end": actual[-1]["value"],
            })
    if not errors:
        return {
            "status": "insufficient_sample", "data_status": "derived",
            "reason": "没有形成可比较的滚动起点。",
        }
    return {
        "status": "ok", "data_status": "derived", "n_origins": origin_count,
        "n_points": len(errors), "horizon_periods": horizon,
        "mae": round(sum(errors) / len(errors), 6),
        "rmse": round(math.sqrt(sum(squared) / len(squared)), 6),
        "direction_accuracy_pct": round(sum(directions) / len(directions) * 100.0, 2)
        if directions else None,
        "envelope_coverage_pct": round(sum(covered) / len(covered) * 100.0, 2)
        if covered else None,
        "origins": origins,
        "method": "滚动起点只使用起点之前的连续历史；基准路径和上/下行包络使用同一规则。",
    }


def _rows_for_config(conn, config):
    table = config["table"]
    frequency = config["frequency"]
    if table == "china_macro_observations":
        query = (
            "SELECT period,value,data_status,source_name,source_url "
            "FROM china_macro_observations WHERE indicator_code=? ORDER BY period"
        )
        params = (config["code"],)
    elif table == "monthly_data":
        # column 来自本文件内的白名单目录，不接收用户输入。
        column = config["column"]
        query = f"SELECT month AS period,{column} AS value FROM monthly_data WHERE {column} IS NOT NULL ORDER BY month"
        params = ()
    elif table == "china_rates_observations":
        query = (
            "SELECT period,value,data_status,source_name,source_url "
            "FROM china_rates_observations WHERE indicator_code=? ORDER BY period"
        )
        params = (config["code"],)
    elif table == "housing_national_observations":
        query = (
            "SELECT period,value,data_status,source_name,source_url "
            "FROM housing_national_observations WHERE indicator_code=? ORDER BY period"
        )
        params = (config["code"],)
    else:
        return []
    try:
        raw = [dict(row) for row in conn.execute(query, params).fetchall()]
    except sqlite3.OperationalError:
        return []
    # LPR 等来源可能是日值，按月取最后一个可见观测，避免把日频误当月频。
    if table == "china_rates_observations" and frequency == "monthly":
        by_month = {}
        for row in raw:
            month = str(row.get("period") or "")[:7]
            if re.match(r"^\d{4}-\d{2}$", month):
                by_month[month] = row
        raw = list(by_month.values())
    return _latest_contiguous_tail(
        _sort_rows(raw, frequency), frequency, config.get("calendar_bridge_month"))


def _catalog_entry(config, rows):
    minimum = _minimum_history(config["frequency"])
    status = "ok" if len(rows) >= minimum else ("insufficient_sample" if rows else "missing")
    return {
        "code": config["code"], "name": config["name"],
        "category": config["category"], "frequency": config["frequency"],
        "mode": config["mode"], "unit": config["unit"],
        "interpretation": config["interpretation"], "status": status,
        "n_obs": len(rows), "sample_start": rows[0]["period"] if rows else None,
        "sample_end": rows[-1]["period"] if rows else None,
    }


def _build_selected(config, rows, horizon, simulations, seed):
    if not rows:
        return {
            "status": "missing", "data_status": "scenario", "code": config["code"],
            "name": config["name"], "reason": "当前数据库没有该指标的可用观测。",
            "history": [], "scenarios": [],
        }
    tail = _latest_contiguous_tail(
        rows, config["frequency"], config.get("calendar_bridge_month"))
    minimum = _minimum_history(config["frequency"])
    result = {
        "status": "ok" if len(tail) >= minimum else "insufficient_sample",
        "data_status": "scenario", "code": config["code"], "name": config["name"],
        "category": config["category"], "frequency": config["frequency"],
        "mode": config["mode"], "unit": config["unit"],
        "interpretation": config["interpretation"], "n_obs": len(tail),
        "sample_start": tail[0]["period"], "sample_end": tail[-1]["period"],
        "latest_value": tail[-1]["value"],
        "latest_source_name": tail[-1].get("source_name"),
        "latest_source_url": tail[-1].get("source_url"),
        "history": tail[-min(120, len(tail)):],
        "scenarios": [], "simulation": None, "backtest": None,
    }
    if len(tail) < minimum:
        result["reason"] = f"连续历史只有{len(tail)}个点，少于{minimum}个点的推演门槛。"
        return result
    scenarios = _scenario_paths(tail, config["frequency"], config["mode"], horizon)
    if not scenarios:
        result["status"] = "insufficient_sample"
        result["reason"] = "变化序列不足，未形成情景路径。"
        return result
    result["scenarios"] = scenarios
    result["simulation"] = _simulate(
        tail, config["frequency"], config["mode"], horizon, simulations, seed)
    result["backtest"] = _backtest(
        tail, config["frequency"], config["mode"], horizon)
    result["method"] = (
        "上行/基准/下行使用连续历史变化的75/50/25分位，并按0.96逐期衰减；"
        "历史仅用于估计规则，未来路径全部标记为scenario。"
    )
    return result


def build_macro_scenario_payload(db_path, indicator=None, horizon=DEFAULT_HORIZON,
                                 simulations=DEFAULT_SIMULATIONS, seed=20260816):
    """构造宏观情景实验室 payload；只读数据库，不写入任何派生结果。"""
    try:
        horizon = max(1, min(MAX_HORIZON, int(horizon)))
    except (TypeError, ValueError):
        horizon = DEFAULT_HORIZON
    try:
        simulations = max(MIN_SIMULATIONS, min(MAX_SIMULATIONS, int(simulations)))
    except (TypeError, ValueError):
        simulations = DEFAULT_SIMULATIONS
    try:
        seed = int(seed)
    except (TypeError, ValueError):
        seed = 20260816
    configs = {item["code"]: item for item in SERIES_CATALOG}
    if indicator and indicator not in configs:
        raise ValueError("未知宏观情景指标")
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        row_map = {code: _rows_for_config(conn, config)
                   for code, config in configs.items()}
        gaps = []
        for item in GAP_CATALOG:
            gap = dict(item)
            mapping = {'CN_INDUSTRIAL_PROFIT': 'CN_IND_PROFIT_YTD_YOY',
                       'CN_CAPACITY_UTILIZATION': 'CN_CAPACITY_UTILIZATION'}
            implemented = row_map.get(mapping.get(item['code'])) or []
            if implemented:
                gap.update(status='implemented_with_data', n_obs=len(implemented),
                           latest_period=implemented[-1]['period'],
                           reason='已接入官方序列，推演能否计算仍由连续样本门槛决定。',
                           next_step='检查历史缺期和统计口径，不用估值补成官方数据。')
            if item['code'] == 'CN_BANK_NIM_NPL':
                try:
                    bank_count = conn.execute("SELECT COUNT(*) FROM china_macro_observations "
                                              "WHERE indicator_code='CN_BANK_NIM_YTD' AND value IS NOT NULL").fetchone()[0]
                except sqlite3.OperationalError:
                    bank_count = 0
                if bank_count:
                    gap.update(status='partial_coverage',n_obs=bank_count,
                               reason='已核验2026Q1/Q2官方银行监管表；更早连续历史和自动图片识别尚未完成。',
                               next_step='继续逐版本核验官方图片；季度不足12期不做统计定位或长期推演。')
            gaps.append(gap)
    catalog = [_catalog_entry(config, row_map[config["code"]])
               for config in SERIES_CATALOG]
    selected_code = indicator or DEFAULT_INDICATOR
    if not row_map.get(selected_code):
        selected_code = next((item["code"] for item in catalog if item["n_obs"]), selected_code)
    selected = _build_selected(
        configs[selected_code], row_map.get(selected_code, []), horizon, simulations, seed)
    return {
        "success": True, "data_status": "scenario",
        "generated_at": datetime.now().isoformat(),
        "selected": selected, "catalog": catalog, "gaps": gaps,
        "parameters": {"horizon": horizon, "simulations": simulations, "seed": seed},
        "methodology": {
            "status_vocabulary": ["scenario", "derived", "official", "cache", "missing", "insufficient_sample"],
            "forecast_boundary": "未来路径是条件情景，不是官方预测；P10/P50/P90不是发生概率。",
            "history_boundary": "只使用当前数据库可见的连续尾段；缺月不桥接、不插值。",
            "backtest_boundary": "回测在每个历史起点重新估计变化分布，不使用起点之后的数据。",
        },
        "warnings": [
            "上行/下行表示指标数值路径较高/较低，不自动等价于整体经济好/坏。",
            "CPI、PPI、失业率、LPR等指标需要结合其他指标解释，不能单指标决定宏观结论。",
            "当前缺口清单只记录未接入内容，不用零值或其他指标代填。",
        ],
    }


__all__ = [
    "SERIES_CATALOG", "GAP_CATALOG", "build_macro_scenario_payload",
]
