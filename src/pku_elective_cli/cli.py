from __future__ import annotations

import argparse
import getpass
import os
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

from .config import load
from .recognizer import Recognizer
from .session import RetryableError, SchoolSession, TerminalCourseError


def _log(message: str) -> None:
    print(time.strftime("%H:%M:%S"), message, flush=True)


def run(config_path: Path, password: str) -> int:
    settings = load(config_path)
    model_dir = Path(__file__).resolve().parents[2] / "models"
    recognizer = Recognizer(model_dir)
    sessions: dict[str, SchoolSession] = {}
    waiting = {target.id: target for target in settings.targets}
    try:
        while waiting:
            groups = defaultdict(list)
            for target in waiting.values():
                groups[(target.identity, target.page)].append(target)
            for (identity, page), targets in groups.items():
                session = sessions.setdefault(identity, SchoolSession(settings, password, recognizer))
                try:
                    if session.login(identity):
                        _log(f"{identity} 身份登录成功")
                    elected, offered = session.fetch(page)
                    index = {(course.name, course.class_no, course.school): course for course in offered}
                    for target in targets:
                        if target.key() in elected:
                            _log(f"[{target.id}] 已在已选列表，停止追踪")
                            waiting.pop(target.id, None)
                            continue
                        course = index.get(target.key())
                        if course is None:
                            candidates = [item for item in offered if item.name == target.name.strip() and item.school == target.school.strip()]
                            if candidates:
                                classes = ", ".join(str(item.class_no).zfill(2) for item in candidates)
                                _log(f"[{target.id}] 找到同名同开课单位课程，但班号不符；页面班号：{classes}")
                            else:
                                _log(f"[{target.id}] 未在第 {page} 页计划中找到")
                        elif course.available:
                            _log(f"[{target.id}] 发现余量 {course.maximum - course.enrolled}（已选/限数：{course.enrolled}/{course.maximum}），提交中")
                            try:
                                _log(f"[{target.id}] {session.submit(course)}")
                            except TerminalCourseError as error:
                                _log(f"[{target.id}] 不再重试：{error}")
                                waiting.pop(target.id, None)
                            except RetryableError as error:
                                _log(f"[{target.id}] 本轮未完成：{error}")
                        else:
                            _log(f"[{target.id}] 暂无余量（{course.enrolled}/{course.maximum}）")
                except TerminalCourseError as error:
                    _log(f"{identity} 身份已停止：{error}")
                    for target in targets:
                        waiting.pop(target.id, None)
                except RetryableError as error:
                    _log(f"{identity} 第 {page} 页暂时失败：{error}")
                    session.identity = None
            if waiting:
                seconds = max(3, settings.refresh_interval * (1 + random.uniform(-settings.random_deviation, settings.random_deviation)))
                _log(f"剩余 {len(waiting)} 门课程；{seconds:.1f} 秒后重试（Ctrl-C 停止）")
                time.sleep(seconds)
    finally:
        for session in sessions.values():
            session.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PKU Auto Elective terminal helper (ONNX / cross-platform)")
    parser.add_argument("--config", type=Path, required=True, help="YAML 配置路径")
    parser.add_argument("--check", action="store_true", help="只校验配置与 ONNX 模型，不发网络请求")
    args = parser.parse_args(argv)
    try:
        settings = load(args.config)
        Recognizer(Path(__file__).resolve().parents[2] / "models")
        if args.check:
            print(f"配置和 ONNX 模型有效：{len(settings.targets)} 门目标课程")
            return 0
        password = os.environ.get("PKU_ELECTIVE_PASSWORD") or getpass.getpass("IAAA 密码（不会保存）：")
        if not password:
            raise ValueError("密码不能为空")
        return run(args.config, password)
    except (OSError, ValueError) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
