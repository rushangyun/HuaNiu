# training/ — 训练

把 PASCAL VOC 训成一个能认出 20 类日常物体的 YOLOv8 模型。
这一目录和后端**只通过权重文件耦合**：它产出 `models/yolo/best.pt`，后端只读这个文件。

## 流程

```bash
# 1. 准备数据（zip 已在 data/VOC/images 时会自动跳过解压）
python training/prepare_dataset.py

# 2. 训练
python training/train.py --epochs 100
```

常用参数：`--batch 16 --imgsz 640 --lr0 0.01 --name 实验名`
（完整列表 `python training/train.py --help`）

## 产出

| 路径 | 说明 |
|---|---|
| `runs/detect/runs/train/<name>/weights/best.pt` | 本次最佳权重 |
| `runs/detect/runs/train/<name>/result.json` | **机器可读的实验结论** |
| `models/yolo/best.pt` | 自动复制过来的"当前最佳"，后端读这个 |

## 数据集

PASCAL VOC 2007 + 2012，20 类，划分与官方数字对齐：

- `train` = VOC2007 trainval(5011) + VOC2012 trainval(11540) = **16551**
- `val` = VOC2007 test(**4952**)

类别见 `configs/voc.yaml`（顺序不能动，改了标签就全错）。

为什么不用 ultralytics 自带的自动下载转换：
它内部的 `safe_download` 走 github.com，在本机代理环境下报
`SSLCertVerificationError`；而且它的划分规则写死的，讲不清也改不动。

## 关于 result.json

这是给 Harness（自主实验闭环）用的接口：每次训练无论成功失败都写一个。
**失败也算实验数据**——显存 OOM 会记成 `error_type: "oom"`，
告诉下一轮"batch 开太大了，往下调"。

```json
{
  "success": true,
  "error": "",
  "error_type": "",
  "hyperparams": { "batch": 16, "imgsz": 640, "lr0": 0.01, ... },
  "metrics": { "mAP50": 0.58, "mAP50_95": 0.37, ... },
  "wall_time_sec": 1234.5
}
```

## 本机实测

RTX 5060 Laptop 8GB：显存占用约 2GB，约 4.4 分钟/epoch（含验证），
100 epochs 约 7 小时。mAP50 在 epoch 7 时约 0.58。
