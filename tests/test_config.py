from pathlib import Path

import numpy as np
import pytest

from pku_elective_cli.config import load
from pku_elective_cli.cli import _password, _read_env_file
from pku_elective_cli.session import IAAA_CALLBACK
from pku_elective_cli.session import SchoolSession
from pku_elective_cli import recognizer as recognizer_module
from pku_elective_cli.recognizer import Recognizer


def test_load_valid_config(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text("user:\n  student_id: 123\ncourses:\n  - id: a\n    name: C\n    class_no: 1\n    school: S\n", encoding="utf-8")
    config = load(path)
    assert config.student_id == "123"
    assert config.targets[0].identity == "bzx"


def test_rejects_fast_refresh(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text("user: {student_id: '1'}\ncourses: [{id: a, name: C, class_no: 1, school: S}]\nclient: {refresh_interval: 2}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="至少为 3"):
        load(path)


def test_accepts_zero_class_number(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text("user: {student_id: '1'}\ncourses: [{id: a, name: C, class_no: 0, school: S}]\n", encoding="utf-8")
    assert load(path).targets[0].class_no == 0


def test_iaaa_callback_uses_registered_http_address():
    assert IAAA_CALLBACK == "http://elective.pku.edu.cn:80/elective2008/ssoLogin.do"


def test_parses_a_second_page_with_one_datagrid_and_all_row():
    document = """<table class='datagrid'><tr class='datagrid-header'><th>课程名</th><th>班号</th><th>开课单位</th><th>限数/已选</th><th>补选</th></tr>
    <tr class='datagrid-all'><td>课程 A</td><td>01</td><td>学院</td><td>20 / 1</td><td><a href='/elective2008/edu/pku/stu/elective/controller/supplement/electSupplement.do?a=1'>补选</a></td></tr></table>"""
    elected, offered = SchoolSession._parse(document)
    assert not elected
    assert offered[0].class_no == 1
    assert offered[0].available


def test_onnx_recognizer_uses_all_time_steps(monkeypatch):
    class Session:
        def run(self, outputs, inputs):
            # time × batch × class: a, blank, b
            return [np.array([[[9., 0., 0.]], [[0., 0., 9.]], [[0., 9., 0.]]])]
    monkeypatch.setattr(recognizer_module, "_preprocess", lambda _: np.zeros((1, 130, 52, 3), dtype=np.float32))
    recognizer = Recognizer.__new__(Recognizer)
    recognizer.session, recognizer.input_name, recognizer.output_name = Session(), "input", "output"
    recognizer.alphabet = ["a", "b"]
    assert recognizer.recognize(b"fixture") == "ab"


def test_normal_course_page_cannot_be_mistaken_for_credit_limit():
    # “学分” is a normal table header, not a server result message.
    document = "<html><body><table><tr><th>学分</th></tr></table></body></html>"
    assert SchoolSession._submission_message(document) is None


def test_reads_only_submission_message_panel():
    document = "<html><body><th>学分</th><td id='msgTips'><table><table><td>图标</td><td>总学分已经超过规定上限</td></table></table></td></body></html>"
    assert SchoolSession._submission_message(document) == "总学分已经超过规定上限"


def test_reads_password_from_dotenv(tmp_path: Path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("# local credential\nexport PKU_ELECTIVE_PASSWORD='secret value'\n", encoding="utf-8")
    monkeypatch.delenv("PKU_ELECTIVE_PASSWORD", raising=False)
    assert _read_env_file(path)["PKU_ELECTIVE_PASSWORD"] == "secret value"
    assert _password(path) == "secret value"


def test_process_environment_overrides_dotenv(tmp_path: Path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("PKU_ELECTIVE_PASSWORD=file-secret\n", encoding="utf-8")
    monkeypatch.setenv("PKU_ELECTIVE_PASSWORD", "shell-secret")
    assert _password(path) == "shell-secret"
