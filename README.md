# product-image-qc — AI 产品图批量质检

**先筛翻车，再人工审。** 把一个文件夹里的 AI 产品图批量过一遍基础质检，
明显不合格的先挑出来，省下逐张肉眼审图的时间。

*Batch QC for AI-generated product images: screen out the obvious failures
locally first, then spend human review time where it matters.*

![python](https://img.shields.io/badge/python-3.9+-blue) ![license](https://img.shields.io/badge/license-MIT-green)

## 它查什么（本地规则版 v1）

| 检查项 | 怎么判 | 结论 |
|---|---|---|
| 文件可读性 / 格式 | 打不开、损坏 | FAIL |
| 分辨率 | 短边 < 800px（可调） | FAIL |
| 宽高比 | 与目标比例不符（可选 1:1 / 3:4 / 9:16 等） | WARN |
| 清晰度 | 边缘强度过低（疑似糊图） | WARN |
| 曝光 | 平均亮度过暗 / 过曝 | WARN |
| 背景干净程度 | 四角颜色偏差过大（棚拍背景不匀） | WARN |
| 近似重复图 | 感知哈希距离过近（同一张图出多遍） | WARN |

输出 `report.csv`（逐图明细）和 `report.md`（汇总），每张图给 PASS / WARN / FAIL。

## 快速开始

```bash
pip install -r requirements.txt   # 只有一个依赖：Pillow
python3 qc.py ./images            # 报告生成在 ./qc-out/
```

可选参数：

```bash
python3 qc.py ./images --ratio 3:4 --min-side 1000 --out ./qc-out
```

示例输出见 [examples/sample-run/report.md](examples/sample-run/report.md)
（5 张演示图：2 PASS / 3 FAIL——低分辨率和重复图都被抓出来了）。

## 它查不了什么（重要）

本地规则**查不了语义问题**：包装标签文字是否完整准确、Logo 是否变形、
产品主体是否被改样。这些恰恰是 AI 产品图最常见的翻车点，必须靠下一层：

1. 人工审图（本工具先把明显翻车的筛掉，人工只看剩下的）；
2. AI 打分接口（路线图 v2：将接入 Gemini Decisions API，用封闭问题批量打分——
   「标签文字是否完整？」「Logo 是否变形？」「背景是否干净？」——低置信度的再转人工）。

工具的定位是质检流水线的**第一道筛子**，不是终审。

## 背景

作者是职业产品摄影师，日常用 AI 给商家批量出产品图和短视频。
出图量一大，逐张审图最耗时间，于是先做了这个筛子自用，现开源出来。
阈值都是经验值，欢迎按自己的品类调参、提 issue 和 PR。

## License

MIT
