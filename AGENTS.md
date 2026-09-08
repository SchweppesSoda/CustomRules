# AGENTS.md

## 源码与产物分支

- 本仓源码主分支是 `master`，日常使用主目录；这是明确的分支例外，不为统一名称改成 `main`。
- `auto-build` 只存生成规则，由 `.github/workflows/sync-rules.yml` 发布。它不是日常开发分支，不直接编辑产物，也不删分支或强推。
- 源码、非规则资源、生成格式与发布合同见 [README.md](./README.md)。

## 日常维护与收尾

- 同仓一次只允许一个任务写入；开始前检查分支、工作树、未提交/未跟踪改动，执行 `git fetch --tags --prune` 核对远程。先辨认遗留改动，落后用 fast-forward，分叉查明原因，不重置覆盖。
- 只有用户明确要求并行或隔离才建立开发临时工作树。CI 的 `auto-build` 发布工作树继续按既有工作流运行。
- 验证后在本地 `master` 留下范围明确的提交；提交前再次核对上游和 staged 范围。推送按用户授权执行，说明是否已触发并完成产物发布。
- `.tmp/` 用于临时输出，`.build/` 可保留编译工具缓存；现场资料、凭据和唯一恢复备份不放这里。清理前检查忽略/未跟踪文件，必要备份放仓库外。
- `.codex/` 只忽略本地可视化预览，不隐藏共享配置。

## 修改边界与验证

- 维护 `sources/`、`scripts/` 或发布流程时，先读 README 和对应 workflow，运行 `python -m unittest discover -s tests -v` 及涉及的构建/验证门禁。
- AirportServers 两份源的生成 marker 由私有配置同步器拥有，受保护的人工条目在 marker 外；改动跨越生成范围时使用 generated-config-sync 工作流。
- 规则修改核对消费者的 URL、分支、格式、behavior 与策略目标。发布产物验证通过后才能切换客户端；不要从旧 source cache 冒充一次新上游抓取。
- `sources/policy-aggregates.toml` 定义按最终策略合并的成员。聚合必须是成员规则的精确去重并集，不能丢弃 classical 条件、跨过其它策略或把不同客户端的来源并成更大的集合；运行 `tests/test_policy_aggregates.py` 及完整构建门禁。旧服务输出在迁移期保留，删除前核对旧配置与 Lite 消费者。
- 文档/忽略规则改动检查链接与 `git diff --check`，不因整理而重建、发布规则或重新部署设备。
- 公共仓库不保存订阅 capability URL、Token、私钥、原始节点配置或设备现场备份。
