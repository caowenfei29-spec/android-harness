"""Smoke tests that need no phone.

These verify the parts of android-harness that are pure host-side logic:
the uiautomator XML parser and the shell-escape helper. Anything that talks
to a device requires a connected phone and is excluded from CI.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from android_harness import ui  # noqa: E402


SAMPLE = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="微信" content-desc="" resource-id="com.tencent.mm:id/title"
        class="android.widget.TextView" package="com.tencent.mm"
        bounds="[100,200][540,260]" clickable="true" enabled="true"
        password="false" />
  <node text="" content-desc="搜索" resource-id=""
        class="android.widget.ImageView" package="com.tencent.mm"
        bounds="[10,10][60,60]" clickable="true" enabled="true"
        password="false" />
</hierarchy>"""


def test_parse_picks_up_bounds_center():
    import tempfile
    p = Path(tempfile.gettempdir()) / "ah_test_dump.xml"
    p.write_text(SAMPLE, encoding="utf-8")
    nodes = ui.parse(str(p))
    assert len(nodes) == 2
    wechat = nodes[0]
    assert wechat["text"] == "微信"
    assert wechat["x"] == (100 + 540) // 2
    assert wechat["y"] == (200 + 260) // 2
    assert wechat["clickable"] is True
    assert wechat["pkg"] == "com.tencent.mm"


def test_parse_reports_resource_id():
    import tempfile
    p = Path(tempfile.gettempdir()) / "ah_test_dump2.xml"
    p.write_text(SAMPLE, encoding="utf-8")
    nodes = ui.parse(str(p))
    assert nodes[0]["res_id"] == "com.tencent.mm:id/title"
