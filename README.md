# PKU Auto Elective CLI

一个无界面的跨平台终端选课辅助工具。它使用 ONNX Runtime 在本机 CPU 上识别验证码，不需要 TensorFlow、Windows WebView2 或图形界面。

本项目仅在补退选开放期间工作，且学校页面、认证协议或规则变化都可能令它失效。请自行确认学校规则和账号安全要求；它不保证速度或选课结果。

## macOS 快速开始

需要 Python 3.11 或更新版本。Apple Silicon 与 Intel Mac 都可使用 ONNX Runtime 的 CPU 版本。

```bash
cd /Users/yaoyin/yy/project/PKUAutoElectiveCLI
python3 -m venv .venv
.venv/bin/pip install -e .
cp config.example.yaml config.local.yaml
# 编辑 config.local.yaml，填写学号和目标课程；不要填写密码
.venv/bin/pku-elective --config config.local.yaml --check
.venv/bin/pku-elective --config config.local.yaml
```

默认会交互式询问密码；也可在当前 shell 设置 `PKU_ELECTIVE_PASSWORD`。密码不写入配置、日志或磁盘。按 `Ctrl-C` 可安全停止。

## 工作方式

每轮依次登录各身份、读取目标课程所在页面、精确匹配“课程名 + 班号 + 开课单位”、仅在有余量时完成验证码校验并提交。已成功、已选、互斥、冲突或权限限制的课程会停止尝试；满员、验证码失败和网络临时故障会在下一轮重试。

该初版采用单进程、单会话的保守策略，避免用并发请求绕过学校限流。`--check` 只验证配置及 ONNX 模型，不会登录学校系统。
