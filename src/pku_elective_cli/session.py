from __future__ import annotations

import html as html_lib
import random
import re
import string
import time
from dataclasses import dataclass
from urllib.parse import urljoin

import requests
from lxml import html

from .config import Settings, Target
from .recognizer import Recognizer

IAAA_HOME = "https://iaaa.pku.edu.cn/iaaa/oauth.jsp"
IAAA_LOGIN = "https://iaaa.pku.edu.cn/iaaa/oauthlogin.do"
BASE = "https://elective.pku.edu.cn/elective2008"
SSO = BASE + "/ssoLogin.do"
# IAAA validates this registered legacy callback literally. It is intentionally
# HTTP (including port 80); the follow-up SSO request below remains HTTPS.
IAAA_CALLBACK = "http://elective.pku.edu.cn:80/elective2008/ssoLogin.do"
SUPPLY = BASE + "/edu/pku/stu/elective/controller/supplement/SupplyCancel.do"
SUPPLEMENT = BASE + "/edu/pku/stu/elective/controller/supplement/supplement.jsp"
CAPTCHA = BASE + "/DrawServlet"
VALIDATE = BASE + "/edu/pku/stu/elective/controller/supplement/validate.do"


class SchoolError(RuntimeError):
    pass


class RetryableError(SchoolError):
    pass


class TerminalCourseError(SchoolError):
    pass


@dataclass(frozen=True)
class OfferedCourse:
    name: str
    class_no: int
    school: str
    maximum: int
    enrolled: int
    href: str

    @property
    def available(self) -> bool:
        return self.maximum > self.enrolled


def _headers(host: str) -> dict[str, str]:
    return {"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8", "Connection": "keep-alive", "Host": host}


class SchoolSession:
    """A conservative single authenticated session for one school identity."""

    def __init__(self, settings: Settings, password: str, recognizer: Recognizer):
        self.settings, self.password, self.recognizer = settings, password, recognizer
        self.http = requests.Session()
        self.http.headers.update(_headers("elective.pku.edu.cn"))
        self.identity: str | None = None
        self.expires_at = 0.0

    def close(self) -> None:
        self.password = ""
        self.http.close()

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        try:
            response = self.http.request(method, url, timeout=self.settings.request_timeout, **kwargs)
        except requests.RequestException as error:
            raise RetryableError(f"网络请求失败：{type(error).__name__}") from error
        if response.status_code in (403, 429):
            raise TerminalCourseError("学校系统已限制访问，程序已停止")
        if response.status_code != 200:
            raise RetryableError(f"学校返回 HTTP {response.status_code}")
        return response

    @staticmethod
    def _page_error(response: requests.Response) -> None:
        tree = html.fromstring(response.text)
        title = "".join(tree.xpath("//title/text() ")).strip()
        if title not in {"系统异常", "系统提示"}:
            return
        text = " ".join(tree.xpath("//text()")).strip()
        for phrase in ("请不要用刷课机", "不在操作时段", "只有同意选课协议"):
            if phrase in text:
                raise TerminalCourseError(phrase)
        if "会话超时" in text or "Token无效" in text or "无验证信息" in text:
            raise RetryableError("会话失效，将重新登录")
        raise RetryableError("学校返回系统异常页")

    def login(self, identity: str) -> bool:
        if self.identity == identity and time.monotonic() < self.expires_at:
            return False
        agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"
        iaaa = requests.Session()
        iaaa.headers.update(_headers("iaaa.pku.edu.cn") | {"User-Agent": agent})
        try:
            home = iaaa.get(IAAA_HOME, params={"appID": "syllabus", "appName": "学生选课系统", "redirectUrl": IAAA_CALLBACK}, timeout=self.settings.request_timeout)
            if home.status_code != 200:
                raise RetryableError(f"统一认证返回 HTTP {home.status_code}")
            reply = iaaa.post(IAAA_LOGIN, data={"appid": "syllabus", "userName": self.settings.student_id,
                              "password": self.password, "randCode": "", "smsCode": "", "otpCode": "", "redirUrl": IAAA_CALLBACK},
                              headers={"Referer": home.url, "X-Requested-With": "XMLHttpRequest"}, timeout=self.settings.request_timeout)
            try:
                payload = reply.json()
            except ValueError as error:
                raise RetryableError("统一认证返回格式异常") from error
            if not isinstance(payload, dict) or not payload.get("success"):
                message = str(payload.get("errors", {}).get("msg", "认证失败")) if isinstance(payload, dict) else "认证失败"
                raise TerminalCourseError(message)
            token = payload.get("token")
            if not isinstance(token, str) or not token:
                raise RetryableError("统一认证未返回 token")
        except requests.RequestException as error:
            raise RetryableError(f"统一认证网络失败：{type(error).__name__}") from error
        finally:
            iaaa.close()
        self.http.cookies.clear()
        self.http.headers["User-Agent"] = agent
        dummy = "JSESSIONID=" + "".join(random.choice(string.ascii_letters + string.digits) for _ in range(52)) + "!1"
        response = self._request("GET", SSO, params={"_rand": str(random.random()), "token": token}, headers={"Cookie": dummy})
        self._page_error(response)
        choices = self._identity_options(response.text)
        if identity == "bfx":
            sida = choices.get("bfx")
            if not sida:
                raise TerminalCourseError("学校未提供辅双身份入口")
            response = self._request("GET", SSO, params={"sida": sida, "sttp": "bfx"})
            self._page_error(response)
        self.identity = identity
        lifetime = self.settings.session_lifetime
        self.expires_at = float("inf") if lifetime == -1 else time.monotonic() + lifetime
        return True

    @staticmethod
    def _identity_options(text: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for sida, kind in re.findall(r"[?&]sida=([A-Za-z0-9]{32})&sttp=(bzx|bfx)", html_lib.unescape(text)):
            result[kind] = sida
        return result

    def fetch(self, page: int) -> tuple[set[tuple[str, int, str]], list[OfferedCourse]]:
        # Subsequent supplement pages contain only the elective-plan table.
        # Read page one first to obtain the authoritative elected-course list.
        first = self._request("GET", SUPPLY, params={"xh": self.settings.student_id}, headers={"Referer": SUPPLY})
        self._page_error(first)
        try:
            elected, first_offered = self._parse(first.text)
            if page == 1:
                return elected, first_offered
            response = self._request("GET", SUPPLEMENT, params={"netui_pagesize": "electableListGrid;20", "netui_row": f"electableListGrid;{(page - 1) * 20}", "xh": self.settings.student_id}, headers={"Referer": SUPPLY})
            self._page_error(response)
            _, offered = self._parse(response.text)
            return elected, offered
        except (IndexError, ValueError, TypeError) as error:
            raise RetryableError("无法解析选课页面；学校页面结构可能已变化") from error

    @staticmethod
    def _parse(document: str) -> tuple[set[tuple[str, int, str]], list[OfferedCourse]]:
        tree = html.fromstring(document)
        tables = tree.xpath('self::table[@class="datagrid"] | .//table[@class="datagrid"]')
        def rows(table):
            header = ["".join(cell.xpath(".//text()")).strip() for cell in table.xpath('.//tr[@class="datagrid-header"]/th')]
            return header, table.xpath('.//tr[@class="datagrid-odd" or @class="datagrid-even" or @class="datagrid-all"]')
        def value(row, header, name):
            cells = row.xpath("./th | ./td")
            return "".join(cells[header.index(name)].xpath(".//text()")).strip()
        elected, plan_header, plan_rows = set(), None, []
        for table in tables:
            header, table_rows = rows(table)
            if not {"课程名", "班号", "开课单位"}.issubset(header):
                continue
            if "补选" in header:
                plan_header, plan_rows = header, table_rows
            else:
                elected.update((value(row, header, "课程名"), int(value(row, header, "班号")), value(row, header, "开课单位")) for row in table_rows)
        if plan_header is None:
            raise ValueError("可选课程表缺失")
        offered = []
        for row in plan_rows:
            cells = row.xpath("./th | ./td")
            quota = value(row, plan_header, "限数/已选").replace(" ", "")
            maximum, enrolled = (int(part) for part in quota.split("/", 1))
            action = cells[plan_header.index("补选")]
            href = action.xpath(".//a/@href")[0]
            offered.append(OfferedCourse(value(row, plan_header, "课程名"), int(value(row, plan_header, "班号")), value(row, plan_header, "开课单位"), maximum, enrolled, href))
        return elected, offered

    @staticmethod
    def _submission_message(document: str) -> str | None:
        tree = html.fromstring(document)
        panels = tree.xpath('.//td[@id="msgTips"]')
        if not panels:
            return None
        cells = panels[0].xpath('.//table//table//td')
        return " ".join((cells[1] if len(cells) >= 2 else panels[0]).xpath(".//text()")).strip() or None

    def submit(self, course: OfferedCourse) -> str:
        captcha = self._request("GET", CAPTCHA, params={"Rand": str(random.random() * 10000)}, headers={"Referer": SUPPLY})
        code = self.recognizer.recognize(captcha.content)
        verified = self._request("POST", VALIDATE, data={"xh": self.settings.student_id, "validCode": code}, headers={"Referer": SUPPLY, "X-Requested-With": "XMLHttpRequest"})
        try:
            if verified.json().get("valid") != "2":
                raise RetryableError("验证码未通过")
        except ValueError as error:
            raise RetryableError("验证码校验响应异常") from error
        if "/supplement/electSupplement.do" not in course.href:
            raise RetryableError("课程提交链接异常")
        response = self._request("GET", urljoin(BASE + "/", course.href), headers={"Referer": SUPPLY})
        self._page_error(response)
        # The document always contains column labels such as “学分”. Only the
        # server's dedicated message panel represents a submission outcome.
        text = self._submission_message(response.text)
        if text is None:
            raise RetryableError("提交后未找到学校结果提示；将下一轮确认，避免重复提交")
        if "补选课程成功" in text:
            return "已提交成功，下一轮将从已选课程列表确认"
        for phrase in ("您已经选过", "上课时间冲突", "考试时间冲突", "总学分已经超过", "学分限制", "只能选其一门", "不符合选课权限", "只能补选"):
            if phrase in text:
                raise TerminalCourseError(phrase)
        if "人数已满" in text or "选课操作失败" in text:
            raise RetryableError(text[:120])
        raise RetryableError(f"学校提交结果未识别：{text[:120]}")
