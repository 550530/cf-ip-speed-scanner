# -*- coding: utf-8 -*-
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt
import app as A

qapp = A.QApplication(sys.argv)
w = A.MainWindow()
w.show()

print("title:", w.windowTitle())
assert "优选IP测速工具" in w.windowTitle(), "窗口标题未改中文"

fake = [
    {"ip": "1.1.1.1", "port": 443, "flag": "JP", "country_name": "日本", "city": "东京",
     "iso": "JP", "latency": 110, "speed": 1.37},
    {"ip": "2.2.2.2", "port": 443, "flag": "JP", "country_name": "日本", "city": "东京",
     "iso": "JP", "latency": 117, "speed": 18.14},
    {"ip": "3.3.3.3", "port": 443, "flag": "JP", "country_name": "日本", "city": "东京",
     "iso": "JP", "latency": 108, "speed": 18.66},
    {"ip": "4.4.4.4", "port": 443, "flag": "JP", "country_name": "日本", "city": "东京",
     "iso": "JP", "latency": 106, "speed": 20.74},
    {"ip": "5.5.5.5", "port": 443, "flag": "JP", "country_name": "日本", "city": "东京",
     "iso": "JP", "latency": 142, "speed": 20.96},
    {"ip": "6.6.6.6", "port": 443, "flag": "JP", "country_name": "日本", "city": "东京",
     "iso": "JP", "latency": 105, "speed": -1},
]
w.on_scan_done(fake)
n = w.tree.topLevelItemCount()
print("rows:", n)
assert n == 6

def sp_of(it):
    t = it.text(4)
    return float(t.split()[0]) if t != "-" else -1

def lat_of(it):
    return int(it.text(3).split()[0])

# 速度降序：已测速部分降序，未测速垫底
w.on_header_sort(4, Qt.DescendingOrder)
sp = [sp_of(w.tree.topLevelItem(i)) for i in range(n)]
print("speed desc:", sp)
done = [v for v in sp if v > 0]
assert done == sorted(done, reverse=True), "速度列未按数值降序"
assert sp[-1] == -1, "未测速未排最后"

# 速度升序：已测速升序，未测速仍垫底
w.on_header_sort(4, Qt.AscendingOrder)
sp = [sp_of(w.tree.topLevelItem(i)) for i in range(n)]
print("speed asc:", sp)
done = [v for v in sp if v > 0]
assert done == sorted(done), "速度列未按数值升序"
assert sp[-1] == -1, "未测速未排最后"

# 延迟升序 / 降序
w.on_header_sort(3, Qt.AscendingOrder)
lat = [lat_of(w.tree.topLevelItem(i)) for i in range(n)]
print("latency asc:", lat)
assert lat == sorted(lat), "延迟列未按数值升序"
w.on_header_sort(3, Qt.DescendingOrder)
lat = [lat_of(w.tree.topLevelItem(i)) for i in range(n)]
print("latency desc:", lat)
assert lat == sorted(lat, reverse=True), "延迟列未按数值降序"

# 右键复制只保留 IP
w.on_header_sort(3, Qt.AscendingOrder)
w.tree.setCurrentItem(w.tree.topLevelItem(0))
w.copy_selection()
clip = A.QApplication.clipboard().text()
first_ip = w.tree.topLevelItem(0).text(0)
print("clipboard:", repr(clip), "first ip:", first_ip)
assert clip == first_ip, "复制内容不是纯 IP"
assert ":" not in clip and "日本" not in clip, "复制夹带了端口/地区"

print("ALL OK")
