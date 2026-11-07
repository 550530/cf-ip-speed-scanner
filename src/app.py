# -*- coding: utf-8 -*-
"""IP Scanner Ultimate - Mega Edition (4888) 复刻版。

纯标准库网络引擎 + PySide6 界面；修复原版「trace 403 导致存活恒为 0」的问题。
"""
import asyncio
import collections
import sys

from PySide6.QtCore import Qt, QThread, Signal, QPoint, QRect, QSize
from PySide6.QtGui import QFont, QColor, QPalette
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QLineEdit, QProgressBar,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QHBoxLayout, QHeaderView, QFrame,
    QSpinBox, QFileDialog, QScrollArea, QComboBox, QSizePolicy, QMenu,
    QAbstractItemView, QWidgetItem,
)

import core
from data import IP_POOLS, REGION_INFO

STYLESHEET = """
QWidget {
    font-family: "Microsoft YaHei", "Segoe UI";
    font-size: 13px;
    background-color: #F3F4F6;
    color: #1F2937;
}
QFrame#CardFrame {
    background-color: #FFFFFF;
    border-radius: 10px;
    border: 1px solid #E5E7EB;
}
QLabel#TitleLabel {
    font-size: 20px;
    font-weight: bold;
    color: #111827;
}
QLabel#WarningLabel {
    color: #DC2626;
    font-weight: bold;
    font-size: 12px;
    padding: 4px 8px;
    background-color: #FEF2F2;
    border-radius: 4px;
    border: 1px solid #FECACA;
}
QLineEdit, QSpinBox, QComboBox {
    border: 1px solid #D1D5DB;
    border-radius: 6px;
    padding: 4px 8px;
    background-color: #F9FAFB;
    min-height: 24px;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #3B82F6;
    background-color: #FFFFFF;
}
QPushButton {
    border-radius: 6px;
    padding: 6px 12px;
    font-weight: bold;
    border: none;
    color: white;
}
QPushButton:disabled {
    background-color: #E5E7EB;
    color: #9CA3AF;
}
QProgressBar {
    border: none;
    background-color: #E5E7EB;
    border-radius: 4px;
    height: 6px;
    text-align: center;
}
QProgressBar::chunk {
    background-color: #3B82F6;
    border-radius: 4px;
}
QTreeWidget {
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    background-color: white;
    alternate-background-color: #F9FAFB;
}
QTreeWidget::item {
    height: 28px;
}
QTreeWidget::item:selected {
    background-color: #EFF6FF;
    color: #1D4ED8;
}
QHeaderView::section {
    background-color: #F3F4F6;
    padding: 4px;
    border: none;
    font-weight: bold;
    color: #4B5563;
}
QScrollArea {
    border: none;
    background: transparent;
}
"""


# ---------------------------------------------------------------- 线程：扫描
class ScannerWorker(QThread):
    progress = Signal(int, int, int, float)   # done, total, alive, elapsed
    status = Signal(str)
    results_ready = Signal(list)              # 阶段1：TCP 存活先回填
    annotated = Signal(dict)                  # 阶段2：逐条补机房标注
    finished = Signal(list)

    def __init__(self, port, ver, prov, running):
        super().__init__()
        self.port = port
        self.ver = ver
        self.prov = prov
        self.running = running

    def run(self):
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        try:
            self.status.emit(f"正在生成 {self.prov} {self.ver} IP库 (目标: 4888个)...")
            items = core.gen_items(self.prov, self.ver, target=4888)
            self.status.emit(f"准备高并发扫描 {len(items)} 个目标 (超时1.0s)...")

            def on_progress(done, total, alive, elapsed):
                self.progress.emit(done, total, alive, elapsed)

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # 阶段 1：TCP 快筛，完成即先回填界面
            res = loop.run_until_complete(
                core.scan_tcp(items, self.port, self.running, on_progress, max_workers=300)
            )
            if self.running["on"]:
                self.results_ready.emit(res)

            # 阶段 2：后台并发 trace 补标注，逐条增量回传
            if res and self.running["on"]:
                def on_one(r):
                    self.annotated.emit(r)
                loop.run_until_complete(
                    core.annotate_all(res, self.running, on_one, max_workers=300)
                )
            loop.close()
            self.finished.emit(res)
        except Exception as e:
            self.status.emit(f"错误: {e}")
            self.finished.emit([])

    def stop(self):
        self.running["on"] = False


# ---------------------------------------------------------------- 线程：测速
class SpeedWorker(QThread):
    progress = Signal(int, int, str)
    status = Signal(str)
    finished = Signal(list)

    def __init__(self, items, running):
        super().__init__()
        self.items = items
        self.running = running

    async def _run_async(self):
        sem = asyncio.Semaphore(5)
        total = len(self.items)
        done = 0

        async def one(item):
            nonlocal done
            async with sem:
                if self.running["on"]:
                    self.status.emit(f"正在测速 [{done + 1}/{total}]: {item['ip']}")
                    sp = await core.download_speed(item["ip"], item["port"], self.running)
                    item["speed"] = sp
                done += 1
                self.progress.emit(done, total, item["ip"])
                return item

        results = await asyncio.gather(*[one(i) for i in self.items],
                                       return_exceptions=True)
        return [x for x in results if isinstance(x, dict)]

    def run(self):
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            res = loop.run_until_complete(self._run_async())
            self.finished.emit(res)
        except Exception as e:
            self.status.emit(f"错误: {e}")
            self.finished.emit([])
        finally:
            loop.close()

    def stop(self):
        self.running["on"] = False


# ---------------------------------------------------------------- 主窗口
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("优选IP测速工具")
        self.resize(1024, 860)
        self.setStyleSheet(STYLESHEET)

        self.scan_worker = None
        self.speed_worker = None
        self.running = {"on": False}
        self.results_map = collections.defaultdict(list)
        self.curr_iso = None
        self.category_btns = []
        self.sort_col = 3
        self.sort_order = Qt.AscendingOrder

        self.setup_ui()

    # ------------------------------------------------------------ UI 搭建
    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        header = QVBoxLayout()
        title_row = QHBoxLayout()
        title = QLabel("🚀 优选IP测速工具")
        title.setObjectName("TitleLabel")
        title_row.addWidget(title)
        title_row.addStretch()
        author = QLabel("作者: Love_Lollipop")
        author.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        title_row.addWidget(author)
        header.addLayout(title_row)
        warn = QLabel("⚠️ 请关闭 VPN 后再使用，否则测速不准")
        warn.setObjectName("WarningLabel")
        header.addWidget(warn)
        main_layout.addLayout(header)

        # 配置行
        config_frame = QFrame()
        config_frame.setObjectName("CardFrame")
        config_layout = QHBoxLayout(config_frame)
        config_layout.setContentsMargins(12, 10, 12, 10)

        config_layout.addWidget(QLabel("端口:"))
        self.port_edit = QLineEdit("443")
        self.port_edit.setFixedWidth(70)
        self.port_edit.setAlignment(Qt.AlignCenter)
        config_layout.addWidget(self.port_edit)
        config_layout.addSpacing(12)

        config_layout.addWidget(QLabel("测速数量:"))
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 2000)
        self.limit_spin.setValue(20)
        config_layout.addWidget(self.limit_spin)
        config_layout.addSpacing(12)

        config_layout.addWidget(QLabel("IP库:"))
        self.prov_combo = QComboBox()
        self.prov_combo.addItems(list(IP_POOLS.keys()))
        self.prov_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        config_layout.addWidget(self.prov_combo)
        main_layout.addWidget(config_frame)

        # 按钮行
        btn_layout = QHBoxLayout()
        self.btn_v4 = self.create_btn("海量扫描 v4 (4888)", "#2563EB", "📡")
        self.btn_v4.clicked.connect(lambda: self.start_scan("v4"))
        btn_layout.addWidget(self.btn_v4)

        self.btn_v6 = self.create_btn("海量扫描 v6 (4888)", "#7C3AED", "📡")
        self.btn_v6.clicked.connect(lambda: self.start_scan("v6"))
        btn_layout.addWidget(self.btn_v6)

        self.btn_speed = self.create_btn("极速测速", "#D97706", "⚡", enabled=False)
        self.btn_speed.clicked.connect(self.start_speed)
        btn_layout.addWidget(self.btn_speed)

        self.btn_save = self.create_btn("保存结果", "#059669", "💾", enabled=False)
        self.btn_save.clicked.connect(self.save)
        btn_layout.addWidget(self.btn_save)

        self.btn_stop = self.create_btn("停止", "#DC2626", "🛑", enabled=False)
        self.btn_stop.clicked.connect(self.stop_task)
        btn_layout.addWidget(self.btn_stop)
        main_layout.addLayout(btn_layout)

        # 进度 / 状态
        self.pbar = QProgressBar()
        self.pbar.setTextVisible(False)
        main_layout.addWidget(self.pbar)

        stat_layout = QHBoxLayout()
        self.lbl_s = QLabel("系统就绪")
        self.lbl_s.setStyleSheet("color: #6B7280;")
        stat_layout.addWidget(self.lbl_s)
        stat_layout.addStretch()
        self.lbl_spd = QLabel("")
        self.lbl_spd.setStyleSheet("color: #6B7280; font-weight: bold;")
        stat_layout.addWidget(self.lbl_spd)
        main_layout.addLayout(stat_layout)

        # 地区筛选
        cat_frame = QFrame()
        cat_frame.setObjectName("CardFrame")
        cat_layout = QVBoxLayout(cat_frame)
        cat_layout.setContentsMargins(12, 10, 12, 10)
        cat_title = QLabel("🌍 地区筛选 (点击切换)")
        cat_layout.addWidget(cat_title)
        self.cat_scroll = QScrollArea()
        self.cat_scroll.setWidgetResizable(True)
        self.cat_scroll.setFixedHeight(100)
        self.flow_w = QWidget()
        self.flow = QVBoxLayout(self.flow_w)
        self.flow.setContentsMargins(0, 0, 0, 0)
        self.cat_scroll.setWidget(self.flow_w)
        cat_layout.addWidget(self.cat_scroll)
        main_layout.addWidget(cat_frame)

        # 结果表
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["IP地址", "端口", "地区/数据中心", "TCP延迟", "下载速度"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setSortingEnabled(False)
        self.tree.header().setSectionsClickable(True)
        self.tree.header().setSortIndicator(3, Qt.AscendingOrder)
        self.tree.header().sortIndicatorChanged.connect(self.on_header_sort)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_menu)
        header_obj = self.tree.header()
        header_obj.setSectionResizeMode(0, QHeaderView.Stretch)
        header_obj.setSectionResizeMode(2, QHeaderView.Stretch)
        self.tree.setColumnWidth(1, 90)
        self.tree.setColumnWidth(3, 110)
        self.tree.setColumnWidth(4, 110)
        main_layout.addWidget(self.tree, 1)

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def create_btn(self, text, color, icon, enabled=True):
        btn = QPushButton(f"{icon} {text}")
        btn.setEnabled(enabled)
        btn.setStyleSheet(
            f"QPushButton {{ background-color: {color}; }} "
            f"QPushButton:hover {{ opacity: 0.9; }}"
        )
        return btn

    # ------------------------------------------------------------ 扫描流程
    def start_scan(self, ver):
        try:
            port = int(self.port_edit.text().strip() or "443")
        except ValueError:
            port = 443
        prov = self.prov_combo.currentText()
        self.toggle_ui(True)
        self._clear_layout(self.flow)
        self.tree.clear()
        self.results_map = collections.defaultdict(list)
        self.curr_iso = None
        self.category_btns = []
        self.running = {"on": True}
        self.scan_worker = ScannerWorker(port, ver, prov, self.running)
        self.scan_worker.progress.connect(self.on_scan_prog)
        self.scan_worker.status.connect(self.lbl_s.setText)
        self.scan_worker.results_ready.connect(self.on_scan_ready)
        self.scan_worker.annotated.connect(self.on_annotated)
        self.scan_worker.finished.connect(self.on_scan_done)
        self.scan_worker.start()

    def _populate(self, res):
        self._clear_layout(self.flow)
        self.results_map = collections.defaultdict(list)
        for r in res:
            self.results_map[r["iso"]].append(r)

        self.category_btns = []
        if not res:
            self.curr_iso = None
            self.refresh_tree()
            return

        sorted_isos = sorted(self.results_map.keys(),
                             key=lambda k: len(self.results_map[k]), reverse=True)
        self.curr_iso = sorted_isos[0]
        for iso in sorted_isos:
            c = REGION_INFO.get(iso, REGION_INFO["XX"])
            btn = QPushButton(f"{c[1]} {c[0]} ({len(self.results_map[iso])})")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton { background-color: #E5E7EB; color: #374151; border-radius: 12px;"
                " border: 1px solid #D1D5DB; } "
                "QPushButton:checked { background-color: #DBEAFE; color: #1D4ED8;"
                " border: 1px solid #3B82F6; }"
            )
            btn.setChecked(iso == self.curr_iso)
            btn.clicked.connect(lambda _, k=iso: self.sel_cat(k))
            self.flow.addWidget(btn)
            self.category_btns.append((iso, btn))

        self.refresh_tree()

    def on_scan_ready(self, res):
        # 阶段1：TCP 存活先回填，地区先用 CIDR hint；阶段2 再逐条补真实机房
        self._populate(res)
        if res:
            self.lbl_s.setText(f"发现 {len(res)} 个存活IP，正在标注机房...")

    def on_annotated(self, r):
        ip = r["ip"]
        for lst in self.results_map.values():
            for i, org in enumerate(lst):
                if org["ip"] == ip:
                    lst[i] = r
                    break
        for it in self.tree.findItems(ip, Qt.MatchExactly, 0):
            it.setText(2, f"{r['flag']} {r['country_name']} - {r['city']}")

    def on_scan_done(self, res):
        self.toggle_ui(False)
        self._populate(res)
        if not res:
            self.lbl_s.setText("未发现符合要求的高质量IP (尝试增加扫描范围或检查网络)")
            return
        self.lbl_s.setText(f"扫描完成，筛选出 {len(res)} 个低延迟IP")

    def sel_cat(self, iso):
        self.curr_iso = iso
        for k, b in self.category_btns:
            b.setChecked(k == iso)
        self.btn_speed.setEnabled(True)
        self.refresh_tree()

    def on_header_sort(self, col, order):
        self.sort_col = col
        self.sort_order = order
        self.refresh_tree()

    def _sort_items(self, items):
        reverse = self.sort_order == Qt.DescendingOrder
        col = self.sort_col
        if col == 4:
            done = [x for x in items if x.get("speed", -1) and x["speed"] > 0]
            miss = [x for x in items if not (x.get("speed", -1) and x["speed"] > 0)]
            done.sort(key=lambda x: x["speed"], reverse=reverse)
            miss.sort(key=lambda x: x["latency"])
            return done + miss  # 未测速始终排最后
        if col == 3:
            return sorted(items, key=lambda x: x["latency"], reverse=reverse)
        if col == 1:
            return sorted(items, key=lambda x: x["port"], reverse=reverse)
        if col == 2:
            return sorted(items, key=lambda x: x["country_name"] + x["city"], reverse=reverse)
        return sorted(items, key=lambda x: x["ip"], reverse=reverse)

    def refresh_tree(self):
        self.tree.clear()
        items = self.results_map.get(self.curr_iso, []) if self.curr_iso else \
            [r for lst in self.results_map.values() for r in lst]
        items = self._sort_items(items)
        for x in items:
            item = QTreeWidgetItem(self.tree)
            item.setText(0, x["ip"])
            item.setText(1, str(x["port"]))
            item.setText(2, f"{x['flag']} {x['country_name']} - {x['city']}")
            item.setText(3, f"{x['latency']:.0f} ms")
            sp = x.get("speed", -1)
            item.setText(4, f"{sp:.2f} MB/s" if sp and sp > 0 else "-")
            if x["latency"] > 300:
                item.setForeground(3, QColor("#DC2626"))
            elif x["latency"] <= 150:
                item.setForeground(3, QColor("#059669"))
            if sp and sp > 0:
                item.setForeground(4, QColor("#D97706"))

    # ------------------------------------------------------------ 测速流程
    def start_speed(self):
        items = self.results_map.get(self.curr_iso, []) if self.curr_iso else \
            [r for lst in self.results_map.values() for r in lst]
        if not items:
            return
        limit = self.limit_spin.value()
        items = sorted(items, key=lambda x: x["latency"])[:limit]
        self.toggle_ui(True)
        self.running = {"on": True}
        self.speed_worker = SpeedWorker(items, self.running)
        self.speed_worker.status.connect(self.lbl_s.setText)
        self.speed_worker.progress.connect(self.on_speed_prog)
        self.speed_worker.finished.connect(self.on_speed_done)
        self.speed_worker.start()

    def on_speed_done(self, res):
        self.toggle_ui(False)
        pmap = {x["ip"]: x for x in res}
        for iso, lst in self.results_map.items():
            for i, org in enumerate(lst):
                if org["ip"] in pmap:
                    lst[i] = pmap[org["ip"]]
        self.refresh_tree()
        self.lbl_s.setText("测速完成")

    # ------------------------------------------------------------ 保存 / 停止
    def save(self):
        items = self.results_map.get(self.curr_iso, []) if self.curr_iso else \
            [r for lst in self.results_map.values() for r in lst]
        if not items:
            return
        path, _ = QFileDialog.getSaveFileName(self, "保存", "_优选IP.txt", "文本 (*.txt)")
        if not path:
            return
        items = sorted(items, key=lambda x: (x.get("speed", -1) < 0, x.get("speed", -1), x["latency"]))
        lines = []
        for x in items:
            sp = x.get("speed", -1)
            sp_str = f"[{sp:.2f} MB/s]" if sp and sp > 0 else ""
            lines.append(f"{x['ip']}:{x['port']} {sp_str} | {x['country_name']}_{x['city']} | {x['latency']:.0f}ms")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        self.lbl_s.setText(f"已保存 {len(items)} 个结果")

    def stop_task(self):
        if self.scan_worker:
            self.scan_worker.stop()
        if self.speed_worker:
            self.speed_worker.stop()
        self.toggle_ui(False)
        self.lbl_s.setText("任务已停止")

    def closeEvent(self, event):
        # 退出前停止并等待后台线程结束，释放 socket / Qt 句柄，避免临时目录被占用
        try:
            self.running["on"] = False
            for w in (self.scan_worker, self.speed_worker):
                if w is not None and w.isRunning():
                    w.stop()
                    w.wait(5000)
            self.scan_worker = None
            self.speed_worker = None
        except Exception:
            pass
        event.accept()

    def toggle_ui(self, busy):
        self.btn_stop.setEnabled(busy)
        self.btn_v4.setEnabled(not busy)
        self.btn_v6.setEnabled(not busy)
        self.btn_speed.setEnabled(not busy and bool(self.results_map))
        self.btn_save.setEnabled(not busy and bool(self.results_map))
        self.pbar.setValue(0)

    def on_scan_prog(self, c, t, alive, sp):
        self.pbar.setValue(int(c / t * 100) if t else 0)
        self.lbl_s.setText(f"扫描: {c}/{t} | 存活: {alive}")
        self.lbl_spd.setText(f"速度: {sp:.0f} IP/s")

    def on_speed_prog(self, c, t, ip):
        self.pbar.setValue(int(c / t * 100) if t else 0)
        self.lbl_spd.setText(f"当前: {ip}")

    def show_menu(self, pos: QPoint):
        menu = QMenu(self)
        act = menu.addAction("复制 IP")
        act.triggered.connect(self.copy_selection)
        menu.exec_(self.tree.viewport().mapToGlobal(pos))

    def copy_selection(self):
        lines = []
        for it in self.tree.selectedItems():
            lines.append(it.text(0))
        if lines:
            QApplication.clipboard().setText("\n".join(lines))


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
