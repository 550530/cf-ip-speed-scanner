# -*- coding: utf-8 -*-
import os, sys, asyncio
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import app as A
import core

qapp = A.QApplication(sys.argv)
w = A.MainWindow()
w.show()
print("window built, combo items:", w.prov_combo.count())
print("columns:", w.tree.columnCount())

# 小批量扫描走引擎，验证 GUI 分组/填表逻辑
running = {"on": True}
items = core.gen_items("Cloudflare (官方全量 - 慢但全)", "v4", 40)
res = asyncio.run(core.batch_test(items, 443, running, lambda *a: None))
w.on_scan_done(res)
print("alive:", len(res), "groups:", {k: len(v) for k, v in w.results_map.items()})
print("tree rows:", w.tree.topLevelItemCount())
print("OK")
