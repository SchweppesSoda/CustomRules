# 从 README 迁出的历史记录

整理日期：2026-09-29。下文保留迁出前的观察与验证结果；日期、版本、待办和完成状态均沿用原文，不代表本次重新测试或当前现场状态。片段中的“当前”“上文”等表述属于原文语境。

来源仓库：`CustomRules`；整理前提交：`8d387ee6491b4d30883ccf6c95dfa181bb4be2bf`。

## 规则聚合首阶段产物数量

来源：`README.md`。

During rollout, existing per-service URLs remain published for older profiles
and Lite clients. This first stage reduces client subscriptions; it adds 10
aggregates (23 files), so a complete build temporarily grows from 475 to 498
files. Removing old exports is a separate step after their consumers have
migrated; fewer subscriptions does not by itself mean fewer published files.

## Network Radar v2.4–v2.6 布局演进

来源：`Egern/Modules/README.md`。

- `20260909-radar-v2.4` 重新分配高度：中号标题 17 pt、标题区 30 pt，底部 8 pt 留白；大号标题区 34 pt。正文改为逐行左右配对的平面表格，承接根容器剩余高度，再按行分配；每个数据单元格仍明确保留中号 13 pt / 大号 20 pt 的可读高度。较高组件的多余空间分配给正文，不在底部堆积。根容器最低预算中号 152 pt、大号 325 pt；服务区固定占用中号 14 pt / 大号 38 pt，不随高度拉伸。
- `20260909-radar-v2.5` 保留上述字号、行距和高度预算，参考 PO0 上报的渐变底与圆角色块：正文背景区分蓝色本地 / 紫色代理，大号分区标题使用更明显的同色底；属性和评分按状态使用绿、琥珀、红或中性色，影视 / AI 使用蓝 / 紫色小块。浅色、深色分别配色；正文与大号服务格仅增加左右 4 pt 内边距，不增加垂直占用。背景直接绘制在原平面表格上，不恢复嵌套弹性卡片。
- `20260909-radar-v2.6` 细化对齐与状态：属性 / 评分的两列边缘和间距与正文一致；大号色块在原有 22 pt 区域内提供上下 3 pt 内边距。中号服务格间距改为 3 pt；未知或关闭用中性色，明确受限用红色，部分可达用琥珀色，正常结果沿用影视蓝 / AI 紫。字号、正文行距和各分区高度预算不变。

## IPv4 镜像核验

来源：`Egern/Modules/README.md`。

2026-09-09 核验镜像无 AAAA、HTTPS 返回 IPv4 及 IPPure 字段；

## v2.6 自动测试与布局检查

来源：`Egern/Modules/README.md`。

v2.6 通过 26 项测试，覆盖出口变化、缓存隔离、IPv4 优先、正常 CAPTCHA 资源与真实挑战页的区分、受限跳转、失败原因、地区与可达语义、中号标题间距、大号七行对应、全字段单行及不同可用高度下的空间分配。浏览器辅助检查使用 329×155 / 360×170 中号和 329×345 / 360×376 大号，包含正常、长字段、全部失败、混合状态及关闭检测，浅色 / 深色共 40 组，检查溢出及属性栏与正文列边缘对齐。新应用的未知、受限、部分可达状态文字与底色对比度均超过 4.5:1。根容器必须按实际组件高度分配空间，浏览器预览不得再把根容器当作内容自适应高度。

## 桌面出口服务探测

来源：`Egern/Modules/README.md`。

2026-09-09 使用实际脚本经桌面 HTTP 适配器验证：Netflix / Disney+ / TikTok 返回页面可达，GPT / Claude / Gemini 返回地区信息。旧判断在前三者正常页面上因 `captcha` 字符串误报验证；Claude 登录页实际返回挑战页。该验证使用桌面出口，不能代表 Egern 设备所选节点；最终字体、SF Symbols、截断及后台刷新仍需设备核对。
