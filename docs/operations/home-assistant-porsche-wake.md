# Home Assistant / Porsche Cayenne 定时唤醒试验

日期：2026-10-12，时区 Europe/Dublin。此方案是实时状态查询试验，不能替代车辆故障修复。

## 环境与版本

- PVE：`hp-pve / 192.168.1.200`；复用 VM105 `home-assistant`，2 核 / 4 GiB / 32 GiB。
- 原系统盘与 EFI 盘保留于 `tank1-zfs`；`onboot=1`，其他 VM/CT 和 ARC 配置不变。
- HA：[http://192.168.1.183:8123/](http://192.168.1.183:8123/)。
- 专用面板：[Porsche 唤醒试验](http://192.168.1.183:8123/porsche-wake/cayenne)。
- Core：`2026.7.2 → 2026.10.1`；Supervisor：`2026.07.5 → 2026.09.3`；HAOS：`18.1 → 18.3`。
- Porsche Connect：稳定版 `0.1.11`，提交 `fce41ad`，依赖 `pyporscheconnectapi==0.2.9`。手动安装，无新增 HACS。
- Matter Server `9.1.1`、Terminal & SSH `10.3.0`、File editor `6.1.0`、Mosquitto `7.1.0`；Supervisor 报告无可用更新，均运行。
- 用户已在 HA 页面完成 Porsche 认证；识别到目标车型 `Cayenne S E-Hybrid (MY24)`。仅绑定此车，不向账户内其他车辆发送唤醒请求。

PVE 历史配置见 [原 VM runbook](https://github.com/007pig/pve/blob/main/docs/home-assistant-vm-runbook.md)。

## 备份与恢复

PVE 私有目录：`/mnt/tank1/backups/recovery/20261012-ha105-porsche/`，root-only。

- `vzdump-qemu-105-2026_10_12-05_07_10.vma.zst`：关机状态创建，主盘、EFI、配置完整；zstd、VMA verify 通过，SHA256 已保存。
- `ha-full-594d8f36.tar`：HA 原生完整备份，包含数据库及四个附加组件；已复制到 VM 外，内部子归档完整读取通过，VM 内外 SHA256 一致。
- 原生备份未加密，恢复不依赖新增密钥；必须保持私有目录权限，不复制到匿名共享或 Git。
- 既有每日 PVE 备份仍沿用 NAS 的共享访问策略（观察到旧 VM105 归档权限为 0660、NAS 映射账户所有）。本次私有备份不改变该既有策略，也不代表日常 VM 归档已加密；有权读取那些归档的账户可能读取 HA 内的凭据。未擅自改动全局备份或 NAS 权限。
- `/config/configuration.yaml.pre-porsche-20261012`：本次追加配置前的私有配置备份。
- HAOS 当前从 B 槽 `18.3` 启动，A 槽 `18.1` 保留。没有通过恢复备份破坏性验证原 VM。

回退优先关闭总开关和调度自动化；删除本次新增配置前先保存审计记录，恢复原配置文件并运行 `ha core check`。系统级回退使用对应原生备份或 PVE 完整备份，保持 VM105 身份；不销毁 VM、不恢复旧路由器配置。

## 自动化与操作

源文件位于本仓库 `homeassistant/`。部署到 HA 的文件包括：

- `/config/custom_components/porscheconnect/`：原项目稳定发布版本。
- `/config/custom_components/porsche_wake_guard/`：本地保护层，统一通过 `button.press` 调用实时查询按钮。
- `/config/packages/porsche_wake.yaml`：五个时间助手、开关、阈值及 automation。
- `/config/porsche_wake_dashboard.yaml`：独立侧栏面板。

Automation：`automation.porsche_wake_scheduler`，每分钟做一次本地检查；没有匹配时刻时不查询 Porsche。按用户最新要求，有效时刻为 **01:00、03:00、05:00、07:00**；第五组预留为 09:00 但关闭。在专用面板修改时间、逐个关闭时段或调整限制。时间以分钟为粒度，秒不参与匹配。`homeassistant/configure_schedule.sh` 可重复写入这组设置，不改变总开关状态。

必须同时启用 automation 和 `input_boolean.porsche_wake_enabled` 才能定时发送。总开关关闭立即阻止新请求；已经提交到 Porsche 的请求无法撤回。手动测试使用面板的 `script.porsche_wake_manual_test`，同样遵守总开关、120 分钟最小间隔和每日最多 4 次。直接在开发者工具按原始按钮会绕过本地保护，不作为日常测试方法。

用户另行明确要求 **2026-10-12 07:00 仍发送一次请求**。通过持久化 `one_off` 精确匹配此日期/时刻：该次最小间隔临时使用 60 分钟，并忽略可选的电量/充电状态跳过；仍遵守认证、限流、按钮可用性、每日上限及去重。该例外不会每天重复，也不补发。使用 `porsche_wake_guard.request_once_at` 配置，在结果实体属性 `one_off_local` 可查看。

本地目标 SOC 为用户选定的 100%，只用于跳过判断，不写入车辆。绝不调用 Direct Charging、Departure Timer、目标电量写入、鸣笛、闪灯或门锁服务。

目标实体：

| 用途 | HA entity_id |
|---|---|
| 实时查询 | `button.cayenne_s_e_hybrid_my24_get_current_vehicle_information` |
| 电量 | `sensor.cayenne_s_e_hybrid_my24_state_of_charge` |
| 充电状态 | `sensor.cayenne_s_e_hybrid_my24_charging_status` |
| 充电功率 | `sensor.cayenne_s_e_hybrid_my24_charging_power` |

实车充电时发现新 API 返回 `CHARGING_RATE.chargingPowerkW`，而原集成读取
`chargingPower`，导致原功率实体仍显示 0。保护层优先读取明确标为 kW 的新字段，
通过 `sensor.porsche_wake_vehicle_power` 在专用面板显示并用于审计/跳过判断；
原集成文件保持官方稳定版不变。新实体每分钟只读取已有缓存，不新增网络请求。

集成没有独立插枪二值实体。保护层从目标车辆原始 `BATTERY_LEVEL`、`CHARGING_SUMMARY`、`CHARGING_RATE` 的 `lastModified` 读取测量时间，取三者最旧值；缺失、无时区或未来时间不视为新鲜。`not_plugged` 状态可作为未连接证据，未知状态不猜测。不把 HA `last_updated` 当作车辆数据时间。

## 安全限制与证据

- 去重记录使用 HA 原子持久化 Store：`/config/.storage/porsche_wake_guard`。请求前先保存本地日期/时刻、每日次数和 pending 标志，保存失败则不发送。
- 秋季重复的 01:00 只处理一次；春季缺失的 01:00 跳过；重启不补发。实际请求间隔按 UTC 秒计算。重启发现未完成请求，按结果未知处理并暂停 24 小时。
- 新鲜且明确的“未插枪、达到目标、正常充电”数据才允许跳过；没有可靠测量时间戳时，按用户选择保持每时刻最多一次的受限请求。
- 失败不立即重试，默认暂停当晚后续请求；认证错误保持人工恢复锁；明确 HTTP 429 至少暂停 24 小时，服务提供的更长 Retry-After 优先。上游没有暴露的状态码或响应头不猜测。
- 上游 `get_current_overview()` 会吞掉部分 Porsche 异常；保护层用仅限当前请求上下文的日志过滤器捕获失败状态码，并丢弃原始日志，防止异常被误报为成功及泄露响应内容。
- 底层 Connection 对部分 HTTP 错误本来会立即重试；保护层通过 HTTPX response hook 在当前受控请求收到首个失败响应时抛出脱敏错误，进入暂停逻辑。仅作用于保护层的请求上下文，普通集成轮询不受该 hook 改变；未修改第三方库文件。[HTTPX 官方机制](https://www.python-httpx.org/advanced/event-hooks/)
- 真实调用仍使用集成按钮，原项目和第三方依赖代码未打补丁。实时接口带 `wakeUpJob`；常规缓存查询不带此参数。
- 实时调用后第 2、第 10 分钟各读取一次目标车缓存，其余观察只看已有状态。缓存请求不带 `wakeUpJob`，不会为了观察再次按按钮；缓存读取失败也会暂停后续唤醒。

日志入口：专用面板中的 `sensor.porsche_wake_result`、automation 的“跟踪”、以及 `/config/porsche_wake_audit.jsonl`。HA Recorder 保留 30 天（原默认配置未设置更长期限），automation 保留最近 100 条 trace；脱敏 JSONL 审计文件持续保留，不自动清理。trace 可能被每分钟调度覆盖，长期证据以审计文件为准。

“Porsche 唤醒结果”在面板中显示中文说明，例如“已查看车辆缓存，未发送唤醒请求”、
“正在请求车辆实时状态”“车辆正在正常充电，本次已跳过”。原始状态码保留在实体属性
`result_code` 及 JSONL 日志的 `result` 字段中；旧历史记录不改写。“实时查询调用成功”
仍明确标注车辆响应待核实，不将服务调用成功等同于车辆唤醒或恢复充电。

`porsche_wake_guard.inspect` 只记录缓存诊断，不访问 Porsche。`porsche_wake_guard.resume` 在重新认证后解除认证暂停，但不清除每日次数、限流冷却或去重历史。

结果必须分层理解：

1. `request_started`：本地已预留并开始调用，不代表服务器接受。
2. `service_returned_success`：按钮调用返回且未捕获库错误，仍不等于车辆醒来。
3. `observation`：后续缓存状态观察；可靠的新测量时间戳才能支持车辆响应判断。
4. 恢复充电还需要功率、状态、SOC 或现场/充电设备证据。仅旧数据变化或调用成功不能证明故障解决。

## 验收记录

- 24 项本地离线测试通过：DST、时刻、去重、跨日、冷却、陈旧/未知状态、并发、持久化失败、认证、限流、吞掉异常、重启未知请求、实车测量结构、缓存查询不重复唤醒、一次性例外及 HTTP 响应拦截等；没有车辆网络调用。
- HA Core 容器内另用实际 `pyporscheconnectapi==0.2.9` 和 HTTPX MockTransport 测试 401/429/503：每种均恰好一次模拟请求，错误未被吞掉，172800 秒 Retry-After 保留。没有外网或车辆请求。
- HA 配置检查通过；Porsche 配置表单可加载，用户已完成认证；原有 15 个集成均 loaded。
- 未绑定实测：保护层返回 `button_unavailable`，请求次数仍为 0，审计文件及持久化记录存在。
- 首次读取车辆缓存：SOC 74%、0 kW、状态 `initialising`。用户确认已插枪，但当前不是 Departure Timer 故障场景，因此本轮不能证明故障已解决。
- VM105 专项 Zabbix 验收通过：VM running、HTTP 成功、检查和两条告警 enabled/recovered、采集新鲜。
- 完整 Zabbix verifier 未通过：既有备份查询当前返回 12 个指标，旧断言硬编码 `length == 9`；实际备份状态为成功、9/9 完成。未修改无关备份断言，也未声称全局监控通过。
- 05:31:56 Europe/Dublin 启动一次受限实时查询，05:32:08 返回；测量时间由 05:26:20 更新到 05:32:06，支持取得车辆新数据。请求计数为 1。SOC 仍 74%、功率仍 0 kW、实际充电状态为 `charging_paused`。早期审计版本将此新增枚举保守记为 `other`；后续版本已补充该枚举，不改写历史日志。
- VM105 正常重启后，Porsche 认证恢复、目标按钮可用；五组助手设置、总开关关闭状态和原去重记录均恢复。随后启用了总开关和调度，并按用户新指示调整为四个时刻。未重启 PVE，因此只验证了 `onboot=1` 配置，没有声称宿主重启已测试。
- 30 分钟内存观察：121 个样本覆盖 1800 秒，最低 MemAvailable 36.81 GiB、最高 full PSI avg10 1.63%、最高区间换出 0.011 MiB/s、新增 OOM 0，全部门禁通过；内核无新增 I/O、EXT4 或 UAS/reset 错误。其他 VM/CT 的状态保持。满载预算余量仍较小，轻载验收不等于并发满载保证。
- 05:34 与 05:42 两次缓存读取成功，完整十分钟观察结束：SOC 74%、0 kW，未观察到恢复充电。用户已明确本次不是故障场景，Departure Timer 故障是否改善仍需后续真实故障窗口验证。
- 今天 07:00 例外已通过 HA 服务写入原子持久化记录，读回为 `2026-10-12|07:00`；离线模拟 07:00 的准入结果为 `send`，不受已执行手动测试的 120 分钟间隔或可选充电状态跳过影响。真实 07:00 尚未到达，不报告为已执行。
- 后续 05:44 检查发现 SOC 升至 75%、状态 `charging`；旧功率实体仍 0。原始测量时间已更新，新增功率字段原因见上文。这个变化支持车辆后来开始充电，但因用户明确不处于故障场景、又没有独立充电桩证据，不能归因于唤醒，也不能宣称 Departure Timer 故障已解决。
- 最终总开关、automation、四个时段均启用，第五组禁用；120 分钟/每日 4 次/100% 本地阈值均读回正确。今天实际发送计数为 1，未修改车辆 Direct Charging（仍 off）或 Departure Timer。
- 最后重载后，新字段读数为 **7.06 kW**，SOC **75%**、状态 **charging**。三项车辆测量一致支持“目前正在充电”；不能由此证明请求导致恢复，或 Departure Timer 故障已修复。07:00 一次性例外、计数 1、pending=false、总开关和 automation=on 再次读回，持久化恢复通过。
