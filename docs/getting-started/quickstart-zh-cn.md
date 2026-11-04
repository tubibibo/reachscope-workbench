# 第一次使用

当前工作台请从仓库根目录运行 `./start-workbench.ps1`，打开
`http://127.0.0.1:8765`，在“新建分析”中按四步选择应用、网站或云资产，再选择检查。
完整说明见 [README](../../README.zh-CN.md) 和 [工作台 API](../reference/workbench-api.md)。

以下保留的是底层 Android 引擎的离线 HTML 演示，不是工作台入口。

先运行演示，不需要 APK、Java 或 AI 账号。

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install .
.venv\Scripts\reachscope demo --out ./reachscope-demo
```

双击 `reachscope-demo/index.html`。左侧目录中每项是一种情况：

- 深链里的数据进入 WebView，再进入桥方法和文件操作。
- 导出入口把 URL 转交给未导出的内部页面。
- 参数写入 `note`，目标读取 `url`，当前分析无法支持这条路径。
- 代码里有候选路径，但签名权限阻止普通应用直接访问入口。
- 清单里声明了入口，却找不到对应实现，因此保留未知。

绿色 SUPPORTED 表示说法与这份静态报告的证据一致；它不是“漏洞已确认”。
REFUTED 只否定正在检查的访问前提；UNDECIDABLE 表示依据不足。
5/5 表示五个演示符合预期，不能解释成实际漏洞检出率。

可以搜索或筛选案例，点击路径节点查看对应源码，使用“逐步回放”跟随已保存的步骤。
右上角可暂停动画，系统的减少动画设置也会生效。点击“调用回放”能看到工具真实执行了哪些查询。
这次演示没有让任何大模型参与，因而也没有模型费用。

准备自己的分析时，先使用 `reachscope doctor` 查看环境。已有解码目录可用
`reachscope index`；APK 文件另需 Java 和 Apktool，可用 `reachscope scan`。
扫描和演示都要求新的或空输出目录，避免混用上次运行的证据。

工具返回的 `artifact_id` 是本次证据的身份。用它查询入口、候选路径和方法，
更换 APK 或分析配置时会得到不同的身份。AI 也通过同样的命令或 Python 函数
使用这些能力。原应用代码可能含敏感信息，应妥善保管本地证据目录。

接下来阅读 [README](../../README.zh-CN.md)、[接口说明](../reference/android-engine-api.md)。开发检查使用
`python scripts/check.py`。已有原项目保留在 F 盘，本交付版是独立目录。
