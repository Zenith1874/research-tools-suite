# 研究画像 schema

每个 `profiles/<profile_id>.json`：

```json
{
  "profile_id": "wfh_rto",
  "name": "远程办公 / 混合办公 / RTO",
  "description": "一句话说明这个项目/兴趣是什么",
  "aspects": {
    "topic":   ["该维度的正例描述，多条，越具体越好"],
    "theory":  ["…"],
    "method":  ["…"],
    "data":    ["…"],
    "setting": ["…"]
  },
  "my_methods_used": ["我已经用过的方法，用于'与我相关但用了我没用过的方法'查询"],
  "weights": {"topic":1.0,"theory":0.8,"method":0.7,"data":0.7,"setting":0.6,"opportunity":0.9},
  "enabled": true
}
```

- `aspects` 各维正例描述会拼进 LLM 提示词，指导它给该画像各维打分。
- `weights` 用于合成 `overall`（加权归一）。
- 新增项目 = 新增一个 json 文件；论文基础标签(aim_paper_labels)只抽一次不受影响，只需重算该画像的 aim_profile_scores。
