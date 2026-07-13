# Qwen2.5-14B-AWQ vs DeepSeek V4-Flash 校准对比

- 校准论文：200篇
- 人工已审：44篇（相关24、边界11、不相关9）
- 分数阈值：60；边界样本不进入正负指标。
- “三画像”指 ai_in_organizations / employee_wellbeing / digital_trace_methods。

## 综合分类（六画像取最高分）

| 模型 | TP | FP | TN | FN | Precision | Recall | FPR |
|---|---:|---:|---:|---:|---:|---:|---:|
| V4-Flash | 22 | 2 | 7 | 2 | 91.7% | 91.7% | 22.2% |
| Qwen14B | 19 | 4 | 5 | 5 | 82.6% | 79.2% | 44.4% |

## 三画像对人工反例的误收

| 画像 | V4误收/9 | V4 FPR | 14B误收/9 | 14B FPR |
|---|---:|---:|---:|---:|
| ai_in_organizations | 1/9 | 11.1% | 2/9 | 22.2% |
| employee_wellbeing | 1/9 | 11.1% | 2/9 | 22.2% |
| digital_trace_methods | 0/9 | 0.0% | 0/9 | 0.0% |

## 阈值敏感性（三画像取最高分）

| 阈值 | V4 FP/9 | V4 Recall | 14B FP/9 | 14B Recall |
|---:|---:|---:|---:|---:|
| 50 | 4/9 | 87.5% | 4/9 | 79.2% |
| 60 | 2/9 | 79.2% | 4/9 | 66.7% |
| 70 | 1/9 | 54.2% | 4/9 | 62.5% |

## 数据纪律

- 14B完整结果：200/200篇。
- 14B标记 uncertainty：76篇。
- 14B产生非逐字证据：39篇、45段；验证器已丢弃，未写入有效证据字段。
- V4-Flash原结果中有非逐字证据：23篇（旧流程未做写入前过滤）。
- 14B画像分存在缺失维度：28/1200行，涉及6篇。
- 最佳分等于0：V4 83篇，14B 125篇；最佳分等于100：V4 0篇，14B 11篇。
- 原始V4-Flash表和主论文库均以只读方式打开。

## 阶段A判定

**未通过，不进入阶段B。** 原提示词下14B同时表现出更高误收、更低召回、分数两极化、画像维度偶发缺失和更高的非逐字证据产生率。建议先收紧画像与JSON schema，再用同一200篇复测。

## 人工反例误收明细

### ai_in_organizations

- V4：3060 Tourists’ Mindsets and the Adoption of ChatGPT for Travel Services: A Moderated-Mediation Model of Self-Efficacy, Anxiet
- 14B：3060 Tourists’ Mindsets and the Adoption of ChatGPT for Travel Services: A Moderated-Mediation Model of Self-Efficacy, Anxiet；24714 Leveraging Semisupervised Learning for Domain Adaptation: Enhancing Safety at Construction Sites through Long-Tailed Obj

### employee_wellbeing

- V4：69930 Well‐being right before and after a permanent nursing home admission
- 14B：24771 Lightweight Active Soft Back Exosuit for Construction Workers in Lifting Tasks；69930 Well‐being right before and after a permanent nursing home admission

### digital_trace_methods

- V4：无
- 14B：无
