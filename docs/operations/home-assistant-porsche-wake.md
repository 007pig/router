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

必须同时启用 automation 和 `input_boolean.porsche_wake_enabled` 才能发送夜间请求。该开关关闭立即阻止新的夜间请求；已经提交到 Porsche 的请求无法撤回。手动测试使用面板的 `script.porsche_wake_manual_test`，同样遵守总开关、120 分钟最小间隔和夜间每日最多 4 次。v1.2 新增独立晚间准备检查，单独最多 1 次实时查询，全天合计最多 5 次。直接在开发者工具按原始按钮会绕过本地保护，不作为日常测试方法。

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

日志入口：专用面板中的 `sensor.porsche_wake_result`、automation 的“跟踪”、以及审计文件。v1.1 起新记录写入 `/config/porsche_wake_audit/YYYY-MM.jsonl`，旧 `/config/porsche_wake_audit.jsonl` 继续可读；每天保留最近 90 天记录。HA Recorder 保留 30 天（原默认配置未设置更长期限），automation 保留最近 100 条 trace。trace 可能被每分钟调度覆盖，长期证据以审计文件为准。

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

## 2026-10-12 07:00 请求实际验收

07:20 Europe/Dublin 只读检查审计日志、持久化计数和 HA 实体缓存；未额外发送唤醒或刷新请求。

| 本地时间 | 证据 |
|---|---|
| 06:52:43 | 请求前已有车辆测量：SOC 100%、`charging_completed`、0 kW |
| 07:00:00.487 | `request_started`，今天 07:00 的一次性例外实际执行，没有因电量达到目标而跳过 |
| 07:00:31.133 | `service_returned_success`；电量、充电状态和功率三项 `lastModified` 均更新至 07:00:23 |
| 07:02:31 | 第 2 分钟缓存读取成功，SOC 100%、充电完成、0 kW |
| 07:04–07:08 | 第 4、6、8 分钟观察记录存在，缓存状态相同 |
| 07:10:32 | 第 10 分钟缓存读取成功，观察完整结束；SOC 100%、充电完成、0 kW |

请求调用成功，且有请求之后的新车辆测量，支持车辆响应判断；没有独立的物理休眠状态信号，
不能由此证明车辆经历了“从深度休眠唤醒”。后续缓存测量时间仍为 07:00:23，不能把每条观察
记录的写入时间当作新的车辆测量时间。07:20 检查时最新可见缓存仍为这组数据。

07:00 前已经充满，前后 SOC 为 100% → 100%、功率为 0 → 0 kW、状态均为充电完成。
这次确认定时请求与车辆新数据通路正常，不能验证“Departure Timer 暂停后恢复充电”，
也不证明原故障已经修复。

计数为当天 2 次（05:31 手动测试 + 07:00 定时请求），pending=false、auth_block=false、
blocked_until=0，一次性例外已消费；本次记录中没有超时、认证或限流错误。总开关与调度
automation 均 on；Direct Charging 仍 off。日常 01:00、03:00、05:00、07:00 策略继续有效。

## 2026-10-13 v1.1：效果记录、观察恢复与 iPhone 通知

用户确认当晚原车设置不变且无人干预。只读回放显示：01:00 请求后十分钟仍为
28%、暂停、0 kW；03:00 请求后先进入初始化，03:03:58 的车辆测量为 30%、charging、
7.14 kW。05:00 因正在充电正常跳过。该记录支持“请求之后观察到暂停后开始充电”，
不独立证明请求的因果作用，更不说明车辆根因已修复。

部署本地保护层 v1.1.0，保留原集成、实体 ID、服务、四个时刻、120 分钟、每日四次及
100% 本地阈值。效果分析、时间线、摘要和数据年龄仅使用已有日志与缓存；仅原有
第 2／10 分钟观察读取云端缓存，不为报告添加额外车辆查询。

### 面板与服务

- 首页增加 `sensor.porsche_wake_effect`（请求／响应／充电变化独立结论）、
  `sensor.porsche_wake_health`（下一时刻、暂停原因、车辆时间、数据年龄）、
  `sensor.porsche_wake_timeline`、`sensor.porsche_wake_night_summary`、
  `sensor.porsche_wake_notification` 和 `sensor.porsche_wake_trial`。
- 第二页“设置与样本”配置实体映射、通知服务、出发核对时间与晨间摘要时间；
  提供日期、插枪／充电需求、无人为干预的确认控件。无法确认的样本不计入有效样本。
- `porsche_wake_guard.refresh_report` 只更新本地面板；`notification_test` 发明确测试通知；
  `confirm_night` 记录指定日期的现场条件。原有 run、inspect、resume 等服务保持。
- 已根据用户确认和实际充电证据登记 2026-10-13 样本；目前 1/7，出发前完成情况需等
  08:00 之后核对。不会根据单晚结果自动减频或更改定时器。

### 通知规则

- 每天 Europe/Dublin 08:05 生成一条晨间摘要，HA 持久通知和已选 iPhone 同步发送。
  08:00 是可编辑的本地核对基准，不写入车辆。08:00 之后的测量不能算作按时完成；
  数据不足时标记无法确认。全天关闭且无执行记录时，仅面板记录未运行，不发空摘要。
- 唤醒失败、认证、限流、日志／状态保存错误和漏执行提示及时通知；同一异常每晚
  去重，原因变化时更新，恢复最多按该异常发送一次。单次十分钟未恢复不作为故障推送。
- 通知任务独立于车辆锁；API 超时 15 秒，不因手机失败重试车辆操作。接口接受不等于
  手机收到。通知按日期／类型持久化去重；摘要允许恢复后至中午 12:00 前补发一次。
- iPhone 已绑定 `notify.mobile_app_xiaoyu_huangs_iphone_2`。用户确认测试通知已收到，
  点击能打开 `/porsche-wake/cayenne`；新版通知服务另一次实际调用也返回 HTTP 200。
  不使用 Critical Alert，不广播到其他设备，不新增公网入口。
- 去重状态保存在 `/config/.storage/porsche_wake_guard_reports`。无法可靠读取或保存
  该状态时暂停手机推送，在 HA 内提示，避免自动重发未知通知。

### 恢复、备份与验收

- 原请求 ledger 新增独立 observation 记录：slot、请求前数据、开始时间、节点游标和
  目标按钮。发送中重启仍按结果未知暂停；观察中重启跳过过期节点，仅继续未来节点，
  每次云端缓存读取前先保存游标，不重发唤醒、不集中补查。
- 最近执行结果从旧／新审计文件恢复；跨日显示次数归零，但不丢失 UTC 冷却记录。
  缺失功率保留未知，不采信库在缺少 chargingRate 时合成的旧 chargingPower=0；
  未来时间和矛盾状态不计作可靠恢复证据。
- 独立本地维护任务每 30 秒检查调度记录与报告。HA 整体停机时仍依赖 PVE/Zabbix，
  不能声称 HA 能在停机期间自行告警。
- 私有备份：VM `/config/.porsche-backups/20261013-v11/before.tar.gz`；PVE
  `/mnt/tank1/backups/recovery/20261013-porsche-v11/before.tar.gz`，完整读取与 SHA256 保存。
  包含原组件、面板、package、ledger、助手恢复数据和旧审计文件。
- 41 项离线测试通过，含今早真实脱敏日志回放、未恢复／初始化／恢复区分、未来数据、
  出发后数据排除、通知失败与去重、摘要时段、观察恢复、日志保留及原有 DST/限流保护。
  HA 配置检查通过，实际新实体、08:00／08:05、iPhone 绑定已核验，车辆请求次数仍为 2。
- 实际 HA 依赖的 401／429／503 模拟测试再次通过，每种只有一次模拟请求；未访问车辆。
  最终重载后，原四个时段、120 分钟／每日 4 次／100%、主开关、两次请求计数和样本确认
  均恢复。首页／设置页所有引用实体存在；通知去重记录保留且没有重启重复推送。
- 下一次自然 08:05 摘要、下一完整充电夜和累计 7 个有效样本的长期结果尚待观察；
  没有用模拟数据冒充这些自然运行验收。

回退先停止本次报告任务并在安全窗口恢复备份中的组件、package 和面板，保留新增审计。
不要用旧 ledger 覆盖已经发生的新请求计数／去重记录；回退前先合并保留新状态。

## 2026-10-13 v1.2：20:00 晚间充电准备检查

新增 `input_boolean.porsche_wake_evening_enabled`，默认 on；
`input_datetime.porsche_wake_evening_time` 默认 20:00，Europe/Dublin。
该开关独立于夜间唤醒开关，在首页“晚间充电准备”卡片修改。
新增 `sensor.porsche_wake_evening_check`，显示检查结论、插枪／Direct 三态值、车辆测量
时间、是否使用实时查询以及通知结果；通知正文也在面板显示。

### 判断与提醒

- 使用相关车辆测量时间，15 分钟内才认为新鲜；不使用 HA 的实体更新时间。
- 明确 `not_plugged` 可判未插枪；新鲜且一致的 charging／instant_charging + 正功率
  可判已连接。暂停、初始化、已完成和单独 0 kW 不能证明已插枪；本车目前没有独立
  插枪实体。车辆库的 connected 属性指在线，未作为插枪信号使用。
- Direct 使用原始 `CHARGING_SUMMARY.mode` 并与同一车辆的 Direct 开关交叉核对。
  缺失／未识别模式、开关 unavailable 或两者矛盾均标未知；off 本身不代表检查通过。
- 缓存不足时最多追加一次受限实时按钮查询，然后给出最终结论。不启动第 2／10 分钟
  观察，不反复刷新。明确正常只记面板；未插枪、Direct、未知或失败合并成一条 HA＋iPhone 通知。
- 文案包含实际检查时间、数据时间和人工检查建议；不切换 Direct、不修改 Departure Timer。
- 按用户后续要求，晚间充电准备提醒及其格式测试使用 iOS Time Sensitive：
  `data.push.interruption-level: time-sensitive`。晨间摘要及其他异常通知保持原等级，
  不使用 Critical Alert；实际专注模式呈现取决于 iPhone 的时效性通知权限。

### 额度、去重与恢复

- 夜间最多 4 次，晚间最多 1 次，实际本地日期内合计最多 5 次。晚间不占夜间额度，
  但与夜间共用 last_attempt、串行锁、120 分钟间隔、认证暂停和限流冷却。
- 所有实时请求共用同一 button.press 方法、5 分钟超时、HTTP 失败不立即重试保护。
  手机失败不会重试车辆查询。正常模式下不能用晚间检查绕过暂停或次数限制。
- 查询前保存 evening_seen／evening_job／独立额度和 pending_purpose。重启发现未完成
  检查则报告结果未知，不重查；已经提交的查询仍按原有未知请求保护处理。
- 默认 20:00 至 21:00 前允许补检一次，超过窗口不补发查询。修改时间后保留一小时窗口；
  跨午夜补检按实际请求日期计算额度，通知和去重仍关联原计划日期。
- 晚间日志使用 purpose=evening_check 与独立 request_id，不进入夜间效果、样本或晨间
  请求统计，也不覆盖最近夜间请求结果。原 refresh_report／confirm_night 仍不会主动查询车辆。

### 验证与回退点

- 57 项离线测试通过，含正常静默、未插枪＋Direct 合并、未知补查一次、查询后仍未知、
  模式缺失但 off、未来／矛盾数据、限流、额度隔离、夜间开关独立、重启不重查、
  手机失败不重试车辆以及自定义时间跨午夜补检。
- HA 配置检查通过，v1.2.0 已加载。新开关 on、20:00、晚间等待状态及面板全部实体已核验；
  原夜间四时段、120 分钟、4 次和 100% 阈值保留。验收时夜间计数 2，晚间 0。
- 最终重载后再次核验晚间开关／20:00、原夜间开关／限制与通知初始化标记均保留，
  晚间仍为等待状态，未提前查询车辆；VM105 和 HA HTTP 专项监控通过。
- 已通过 evening_notification_test 发送明确“格式测试，不是车辆实际状态”的模拟通知；
  接口返回 HTTP 200，手机实际送达待用户确认。测试没有查询车辆。
- 当前缓存读到充电完成、Direct 开关 off、模式无法明确解析，正确保留“无法确认”；
  不将这一状态报为插枪及模式检查通过。首个自然 20:00 检查尚待验收。
- 私有备份：VM `/config/.porsche-backups/20261013-v12/before.tar.gz`；PVE
  `/mnt/tank1/backups/recovery/20261013-porsche-v12/before.tar.gz`。归档完整读取通过，SHA256 已保存。
  包含 v1.1 组件、package、面板、主 ledger、报告去重状态和助手恢复数据。

回退时可先关闭晚间检查独立开关；不要清除已发生的实时请求计数、last_attempt 或限流记录。
