# -*- coding: utf-8 -*-
import os, sys, asyncio
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import app as A, core

qapp = A.QApplication(sys.argv)
w = A.MainWindow()
running = {"on": True}
for _ in range(2):
    items = core.gen_items("Cloudflare (官方全量 - 慢但全)", "v4", 30)
    res = asyncio.run(core.batch_test(items, 443, running, lambda *a: None))
    w.on_scan_done(res)
    print("pass alive:", len(res), "flow buttons:", w.flow.count(), "tree:", w.tree.topLevelItemCount())
# 测速回填路径
if w.results_map:
    grp = list(w.results_map.values())[0][:3]
    sw = A.SpeedWorker(grp, running)
    sw.run()
    w.on_speed_done(grp)
    print("speed backfill OK, rows:", w.tree.topLevelItemCount())
print("OK2")
