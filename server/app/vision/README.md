# app/vision — 视觉推理与推流（只负责"算"和"发"）

| 文件 | 干什么 | 为什么不这么干不行 |
|---|---|---|
| `detector.py` | YOLO 推理 | ① **延迟加载 torch**：把 `from ultralytics import YOLO` 放进函数里 —— 它一 import 就占几百 MB 显存，纯对话场景绝不能加载；② **同步阻塞推理丢线程池**（`run_in_executor`） —— ultralytics 的 predict 是同步阻塞的，直接 await 会**卡死 FastAPI 事件循环**，前端打字机效果一卡一卡 |
| `stream.py` | 采集摄像头 → MJPEG 分段推流 | 输出 MJPEG，浏览器 `<img>` **直接显示**，前端不用引入任何解码库；多连接共享一路采集+推理，靠**引用计数**管理摄像头生命周期（最后一个人走了自动释放） |

## 耦合方式

和后端其它层**只通过权重文件耦合**：`training/` 产出 `models/yolo/best.pt`，这里只读它。
所以不训练也能跑对话（只是"看不见"，视觉工具会提示模型未就绪）。

## 本机实测

RTX 5060 Laptop 8GB：显存占用约 2GB，约 4.4 分钟/epoch（含验证）。
`best.pt` 停在 34 epoch 时 mAP50 = 0.804。
