# 优选IP测速工具（CF / CDN 优选 IP 扫描测速）

> 作者：Love_Lollipop
> 纯 Python 复刻版：PySide6 界面 + 标准库 asyncio/socket/ssl 网络引擎，单文件 exe 打包。

一款用于扫描 Cloudflare / Gcore / CloudFront 等 CDN anycast 优选 IP，并按 TCP 延迟、
下载速度排序的 Windows 桌面工具。本仓库是对原版 `IP Scanner Ultimate` 复刻修复后的源码工程。

## 修复背景

原版在 TCP 探测达标后，强制要求 `http://<裸IP>/cdn-cgi/trace` 返回 200 并解析出机房代码；
该请求用**裸 IP 做 Host**，被 Cloudflare 边缘直接 **403（error 1003）**，trace 永远失败，
每个 IP 都被硬过滤丢弃，导致**存活恒为 0、列表为空**。

复刻版的修复要点：

- trace 使用正确 Host/SNI = `www.cloudflare.com`，先 80 明文、失败回退 443 HTTPS（证书不校验）；
- trace 拿不到机房代码时**不再丢弃 IP**，回退使用网段自带地区标签标注；
- 网络引擎改用标准库 asyncio/socket/ssl，不依赖 aiohttp，减少打包体积与运行时故障点。

完整根因证据链与本机实测记录见 [`根因分析与使用说明.md`](根因分析与使用说明.md)。

## 功能特性

- 8 个候选 IP 池（CM 亚洲极速 / CM 移动综合 / CT 电信 / CU 联通 / CF 国内混合 / Gcore / CloudFront / CF 官方全量），支持 v4 / v6 扫描；
- **两阶段扫描**：阶段 1 高并发 TCP 快筛，存活结果立即回填界面；阶段 2 后台并发 trace 补真实机房标注，不阻塞显示，消除末尾长尾卡顿；
- 极速测速：5 路并发下载样本测速（MB/s），保留已读样本估算速度；
- 表头点击排序（IP / 端口 / 地区 / TCP 延迟 / 下载速度），延迟、速度按数值排序，未测速条目排最后；
- 地区分组筛选、结果导出 txt；右键复制只保留纯 IP；
- 关闭窗口时停止后台线程并释放 socket / Qt 句柄，降低临时目录占用导致的退出弹窗。

## 目录结构

```
.
├── README.md
├── requirements.txt          # 运行依赖（PySide6）；打包依赖见下文
├── 根因分析与使用说明.md
└── src/
    ├── app.py                # PySide6 界面 + 扫描/测速线程
    ├── core.py               # 扫描 / trace / 测速核心引擎（纯标准库）
    ├── data.py              # IP 池 CIDR / 地区表 / 机房 colo 映射
    ├── IPScannerUltimate.spec
    ├── smoke.py              # 界面回归脚本
    ├── smoke2.py             # 两阶段扫描 + 测速回填回归
    ├── smoke3.py             # 排序 / 右键复制回归
    └── speed_test.py         # 单 IP 下载测速 CLI 小工具
```

## 环境要求

- Windows 10 / 11
- Python 3.10+（开发验证于 3.13）
- 运行依赖：`PySide6`；引擎本身为标准库，无其它第三方依赖

## 从源码运行

```powershell
cd src
pip install -r ..\requirements.txt
python app.py
```

## 打包单文件 exe（onefile）

```powershell
cd src
pip install pyinstaller>=6.0
pyinstaller --noconfirm --onefile --windowed --name IPScannerUltimate app.py
# 产物：dist\IPScannerUltimate.exe（单文件，无附带文件夹）
```

也可直接使用 `src\IPScannerUltimate.spec`：

```powershell
cd src
pyinstaller --noconfirm IPScannerUltimate.spec
```

## 已知限制

- **CF anycast 机房由边缘路由动态分配**，与候选网段不是固定绑定；同一段不同 IP 速度可差数十倍。网段偏置只提高近机房命中概率，最终快慢以「下载速度」列实测排序为准，建议多扫几轮或换池对比。
- onefile 首次启动需解压到临时目录，会慢几秒；请正常点窗口关闭按钮退出，不要用任务管理器强杀（强杀会留 `_MEI` 临时目录残留）。
- 中国大陆网络到 CF 边缘延迟普遍 150–300ms 属正常直连水平；测速值反映当前链路带宽，慢时段整体偏低属线路因素。
- trace 未收录的机房代码会显示为「未知节点」，地区回退到网段标签。

## 免责声明

本项目仅供学习与网络测速研究使用，请遵守当地法律法规及对应 CDN 服务商的使用条款；
不得用于任何未经授权的扫描、攻击或违反服务条款的行为。
