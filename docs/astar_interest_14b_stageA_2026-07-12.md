# A* 兴趣抽取：Qwen2.5-14B 阶段A校准记录

日期：2026-07-12  
执行节点：`iverson.cs.nmsu.edu`（用户 `zcui`）  
状态：阶段A完成；未通过；阶段B未启动。

## 目标与边界

- 使用本地 `Qwen/Qwen2.5-14B-Instruct-AWQ` 对与V4-Flash完全相同的200篇校准论文运行原始 `aim-v1` 提示词。
- 主论文库 `pboc_data.db` 和V4-Flash派生库 `data/astar_interest.db`只读。
- 14B结果写入独立数据库及独立表，不覆盖现有标签或分数。
- 本轮只做baseline，没有把人工抽查提出的三条画像收紧规则加入提示词。

## 环境

- GPU：NVIDIA RTX 4000 Ada Generation，20,475 MiB。
- 虚拟环境：`/home/simurghnobackup/zcui/venvs/reddit_env`。
- Python 3.13.13；PyTorch 2.11.0+cu130；vLLM 0.25.0。
- Hugging Face缓存：`/home/simurghnobackup/zcui/hf_cache`。
- 模型checkpoint：9.29 GiB；运行时显存约18.3 GiB；KV缓存约6.66 GiB。
- vLLM只绑定 `127.0.0.1:8000`；阶段A完成后已停止，GPU已释放。

安装时服务器缺少Python开发头文件，另用 `uv` 在共享盘安装Python 3.13.12用户态运行时，
并通过 `CPATH`提供兼容的 `Python.h`。服务器FFmpeg与 `torchcodec` 不兼容；由于本任务为纯文本，
卸载本次随vLLM新增的 `torchcodec`，让vLLM使用无视频依赖路径。Triton、TorchInductor和vLLM编译缓存均放到 `/tmp`。

## 输入与运行

输入：`outputs/calibration_input_200.jsonl`，200行，200个唯一article ID，全部有摘要。

远端目录：

```text
/home/simurghnobackup/zcui/astar_interest_14b_stageA/
```

服务命令封装在 `scripts/start_vllm_iverson.sh`。抽取命令：

```bash
python scripts/aim_calibrate_local14b.py \
  --input outputs/calibration_input_200.jsonl \
  --profiles profiles \
  --output-db outputs/astar_interest_14b_calibration.db \
  --base-url http://127.0.0.1:8000/v1 \
  --model Qwen/Qwen2.5-14B-Instruct-AWQ \
  --workers 3
```

首轮完成192/200，耗时951.5秒；8篇因模型把 `country/time_range` 返回为数组而未写入。
增加保守文本规范化后断点补跑，49.9秒完成剩余8篇。最终：

- `aim_paper_labels_14b`：200行。
- `aim_profile_scores_14b`：1,200行（200×6画像）。
- 最终失败：0。
- 模型与输入哈希用于断点跳过；每篇成功后立即提交SQLite事务。

## 校准结果

人工已审44篇：相关24、边界11、不相关9；阈值60，边界不进入正负指标。

| 模型 | Precision | Recall | FPR |
|---|---:|---:|---:|
| V4-Flash | 91.7% | 91.7% | 22.2% |
| Qwen2.5-14B-AWQ | 82.6% | 79.2% | 44.4% |

三画像对9篇人工反例的误收：

- `ai_in_organizations`：V4 1/9；14B 2/9。
- `employee_wellbeing`：V4 1/9；14B 2/9。
- `digital_trace_methods`：两者均0/9。

数据纪律与稳定性：

- 14B模型或逐字证据验证器标记 `uncertainty` 76篇。
- 14B产生45段非逐字证据，涉及39篇；写入前验证器已全部丢弃。
- 14B有28/1,200条画像分缺少至少一个维度，涉及6篇。
- 14B最佳分为0的论文125篇、最佳分为100的论文11篇，较V4明显两极化。

## 判定与后续

阶段A未通过，未运行约1万候选的阶段B。下一轮应继续使用同一200篇：

1. 收紧 `ai_in_organizations`、`employee_wellbeing`、`digital_trace_methods` 的纳入与排除规则。
2. 用严格JSON schema要求六个画像的六个维度全部存在。
3. 缺任一维度时不计算综合分，避免按剩余维度重新归一导致分数膨胀。
4. 要求evidence从提供的摘要中复制，保留当前逐字验证器。
5. 复测通过后才能进入阶段B。

详细逐篇结果：`outputs/compare_14b_vs_v4flash.csv`。  
汇总：`outputs/compare_14b_vs_v4flash_summary.md`。
