from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Target:
    id: str
    name: str
    class_no: int
    school: str
    page: int = 1
    identity: str = "bzx"

    def key(self) -> tuple[str, int, str]:
        return self.name.strip(), self.class_no, self.school.strip()


@dataclass(frozen=True)
class Settings:
    student_id: str
    targets: tuple[Target, ...]
    refresh_interval: float = 6.0
    random_deviation: float = 0.2
    request_timeout: float = 60.0
    session_lifetime: int = 600


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} 必须是对象")
    return value


def load(path: Path) -> Settings:
    raw = _mapping(yaml.safe_load(path.read_text(encoding="utf-8")) or {}, "配置文件")
    user = _mapping(raw.get("user", {}), "user")
    client = _mapping(raw.get("client", {}), "client")
    student_id = user.get("student_id", "")
    if isinstance(student_id, bool) or student_id is None or not str(student_id).strip():
        raise ValueError("user.student_id 必须填写")
    entries = raw.get("courses")
    if not isinstance(entries, list) or not entries:
        raise ValueError("courses 至少需要一门课程")
    targets = []
    for index, entry in enumerate(entries, 1):
        item = _mapping(entry, f"courses[{index}]")
        try:
            target = Target(str(item["id"]), str(item["name"]), int(item["class_no"]), str(item["school"]),
                            int(item.get("page", 1)), str(item.get("identity", "bzx")))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"courses[{index}] 字段不完整或格式错误") from error
        if not target.id.strip() or not all((target.name.strip(), target.school.strip())):
            raise ValueError(f"courses[{index}] 的 id、name、school 不能为空")
        # The school uses 00 as a legitimate class number, which normalizes to
        # integer 0 after parsing. Course number and class number are distinct.
        if target.class_no < 0 or not 1 <= target.page <= 999 or target.identity not in {"bzx", "bfx"}:
            raise ValueError(f"courses[{index}] 的班号、页码或身份无效")
        targets.append(target)
    if len({target.id for target in targets}) != len(targets):
        raise ValueError("课程 id 不能重复")
    interval = float(client.get("refresh_interval", 6))
    deviation = float(client.get("random_deviation", 0.2))
    timeout = float(client.get("request_timeout", 60))
    lifetime = int(client.get("session_lifetime", 600))
    if interval < 3 or not 0 <= deviation <= 0.9 or timeout < 1 or lifetime == 0 or lifetime < -1:
        raise ValueError("client 参数无效：refresh_interval 至少为 3 秒")
    if interval * (1 - deviation) < 3:
        raise ValueError("随机后的最短刷新间隔不得少于 3 秒")
    return Settings(str(student_id).strip(), tuple(targets), interval, deviation, timeout, lifetime)
