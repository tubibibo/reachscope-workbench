# 浏览器验收

这里集中保存跨 API 与前端的浏览器验收脚本。`check_*.py` 是显式命令行入口，
不是 pytest 的 `test_*.py` 单元测试，不会因测试收集自动启动服务或浏览器。

统一运行：

```console
python scripts/quality/check_browser.py
```

默认输出 `artifacts/validation/browser/`，可以使用 `--out` 指定仓库外目录，
或使用 `--browser` 指定本机 Chromium/Edge。八组完整门禁使用新建工作区与
本地 fixture；不复用用户的 `.workbench/`、AI 密钥或商业模型服务。

保留的 `check_legacy_*.py` 和额外专项入口是历史兼容验收工具，不能仅凭目录
存在就视为已被当前八组门禁执行。查看完整门禁应以 `check_browser.py` 的调度为准。
