# PKU Auto Elective CLI

面向北京大学补退选阶段的终端选课辅助工具。项目以 Python 实现选课会话、课程页面解析与调度逻辑，并使用 ONNX Runtime 执行本地验证码推理。它提供无界面的命令行工作流，适用于 Windows、macOS 和 Linux 环境。

> 本工具仅供学习、研究和在学校规则允许范围内的个人使用。学校系统、认证流程、课程页面和访问策略可能随时变化；请自行评估风险并承担使用后果。项目不保证选课结果，也不应被用于规避学校的访问限制。

## 功能

- 支持多个目标课程，逐项按“课程名 + 班号 + 开课单位”精确匹配。
- 支持主修 (`bzx`) 与辅双 (`bfx`) 身份，以及补退选页面 1–999。
- 登录、查询、验证码校验与提交均在同一终端进程中完成；目标课程独立跟踪。
- 展示实时余量及原始“已选/限数”数据。
- 支持交互式输入密码、环境变量及 `.env` 文件；密码不会写入配置或日志。
- 提供 `--check` 离线检查配置与模型完整性，不会访问学校系统。

## 安装

项目要求 Python 3.11 或更新版本。推荐使用 [uv](https://docs.astral.sh/uv/) 创建隔离环境：

```bash
git clone <your-fork-or-repository-url>
cd PKUAutoElectiveCLI
uv sync --group dev
```

也可使用标准虚拟环境：

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

## 配置

复制模板并填写学号、目标课程：

```bash
cp config.example.yaml config.local.yaml
```

示例：

```yaml
user:
  student_id: "YOUR_STUDENT_ID"

courses:
  - id: software-practice
    name: "互联网软件开发技术与实践"
    class_no: 0       # 班号 00 写作整数 0；不是课程号
    school: "软件与微电子学院"
    page: 2
    identity: bzx

  - id: another-course
    name: "另一门课程"
    class_no: 1
    school: "开课单位"
    page: 1
    identity: bzx

client:
  refresh_interval: 6
  random_deviation: 0.2
  request_timeout: 60
  session_lifetime: 600
```

`class_no` 指的是页面“班号”列，而不是“课程号”。刷新间隔的随机下界不得小于 3 秒。

## 密码来源

按以下优先级取得 IAAA 密码：

1. 环境变量 `PKU_ELECTIVE_PASSWORD`；
2. `--env-file` 指定的文件，默认项目当前目录的 `.env`；
3. 终端交互式输入。

创建本地凭据文件：

```bash
cp .env.example .env
```

然后编辑 `.env`：

```dotenv
PKU_ELECTIVE_PASSWORD="YOUR_IAAA_PASSWORD"
```

`.env` 与 `config.local.yaml` 已被 Git 忽略，切勿提交包含真实密码的文件。若 `.env` 不在当前目录，可传入 `--env-file /path/to/.env`。

## 运行

先做离线自检：

```bash
uv run pku-elective --config config.local.yaml --check
```

开始运行：

```bash
uv run pku-elective --config config.local.yaml
```

按 `Ctrl-C` 停止。程序会对每一门尚未完成的目标课程轮询；当课程已在“已选列表”中确认，或学校返回明确的冲突、权限、学分等不可重试结果时，停止追踪该课程。网络波动、满员与验证码失败会进入后续轮次。

## 项目来源与许可

本项目参考了 [Aerisun/PKUAutoElective2026](https://github.com/Aerisun/PKUAutoElective2026) 的部分实现。上游项目延续自 `zhongxinghong/PKUAutoElective` 与 `Hovennnnn/PKUAutoElective2023`；相关模型与第三方声明见 [NOTICE.md](NOTICE.md)。

本项目以 [MIT License](LICENSE) 发布。

## 责任须知

- 你可以修改和使用这个项目，但请自行承担由此造成的一切后果
- 严禁在公共场合扩散这个项目，以免给你我都造成不必要的麻烦
