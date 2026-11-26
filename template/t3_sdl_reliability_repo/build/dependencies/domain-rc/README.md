# 领域规则检查

五个 Python 模块分别提供正交几何净宽、电源质量、水路连通性、热量守恒及蓄冷、新风量及夏季换气计算。领域算法使用显式工程单位。规范条号、适用条件、限值、引用及签核状态由使用方绑定。

## 构建入口

在项目中锁定 domain-rc 后，用命名目标声明 scope、上游依赖和输出。源文件位于项目源或资产目录；消费构建结果时显式写入 dependencies。示例在[机柜液冷接管](../../examples/domain-rc/texsys.toml)。

| 目标                           | scope 输入                                                                             | 结果                                                         |
| ------------------------------ | -------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| domain-rc:schematic-netlist    | schematic，领域原理接续 JSON                                                           | 原理网表                                                     |
| domain-rc:diagram-netlist      | drawing，Texsys 原理图 JSON；selection，模型摘要、专业接口种类映射及范围               | 原理图中所选端口的网表                                       |
| domain-rc:air-filtration-paths | network，按工况声明的送风网络及过滤器清单 | 末端可达路径的过滤级数范围、代表路径及可能成为末级的过滤器 |
| domain-rc:airflow-boundaries   | scene，带分区和已标注开口的米制静态 USD                                                | 分区、共墙、已定位开口的两侧区域、面积及未决项               |
| domain-rc:airflow-netlist      | boundaries，实施侧开口清单                                                             | 每区一个集总端口、每个开口一条接续的 HVAC 物理网表           |
| domain-rc:zonal-pressure       | boundaries，实施侧开口清单；schedule，独立运行工况表                                   | 各区压力、逐开口流量、逐区残差及指定压差的净送风量           |
| domain-rc:drainage-paths       | installation，安装中心线、地漏坐标、候选排放段序列及阀门端口                           | 逐地漏核实的管段与接入里程、阀端里程、未决路径               |
| domain-rc:tailwater-study      | paths，已安装排水路径和阀端位置；schedule，回水工况与阀门额定资料                      | 每个地漏的静态水位裕量、逐阀承受水头与额定裕量、未决观测     |
| domain-rc:equipment-clearances | scene，米制正交设备布置；selection，设备、空间、障碍、可选拆装任务及源修订 | 设备六面的世界坐标净距、控制对象、碰撞和指定任务的拆装包络 |
| domain-rc:cooling-service-netlist | scene，米制正交布置；selection，设备、房间和有序服务中心线的图元清单 | 从设备和房间包络提取的 HVAC 服务网表、端点坐标、候选对象及未决接续 |
| domain-rc:cooling-dispatch | network，实施侧服务网表；plan，独立设计接续；schedule，设备分配和停运工况 | 可用路线，逐笔已核实、未决及未送达的计划 kW，逐机和逐房合计 |
| domain-rc:cooling-redistribution | network、plan，同版服务网络与设计接续；performance，工况产品性能；study，分区需求、停运对象及路线容量 | 给定独立路线及可调分配条件下的最大同时供冷量、分配方案和最小割证据 |
| domain-rc:cooling-performance | catalog，按型号和出处登记设备性能点；conditions，各工况的室外温度 | 每台设备的可用冷量、COP、插值区间和缺少依据的工况 |
| domain-rc:clearance-profile    | scene，米制 Z 向上的静态 USD；route，运输路线标识                                      | 直线路线的站位断面、可通行横向区间、门洞、障碍及清单完整性   |
| domain-rc:physical-netlist     | layout，端口布置 JSON 或展平的静态米制 USD                                             | 物理网表、来源摘要和未决端点                                 |
| domain-rc:physical-federation  | spec，项目发图与设备对照清单；netlists，各成员名到物理网表路径的映射                   | 保留各域连接、端口和来源的项目物理网表，逐设备核对跨专业接口 |
| domain-rc:dew-margin-history | plan，管段、测点及必验时窗；observations，独立记录及其温度与时钟误差 | 各共同观测时段的表温、露点、温差区间及未覆盖时段 |
| domain-rc:project-lvs | spec，已签发的端口清单；schematics 与 netlists，各成员的原理与实施网表 | 按资产和成员归集指定端口的一致、差异、未决数量及接续证据 |
| domain-rc:fuel-endurance | inventory，与实施场景绑定的油箱有效升数及供油机组；schedule，必验工况及各运行机组的 L/h | 各油箱的控制工况、储油时长、已知耗油给出的时长上界、缺失的工况或机组耗油 |
| domain-rc:ups-discharge-curves | scene，实际 UPS 图元；catalog，产品交流输出放电曲线；selection，逐台选型及电池运行条件 | 按 UPS 交付适用的曲线点、工况、安装及产品依据，另列未决设备 |
| domain-rc:generator-ratings | scene，机组实施布置；catalog，产品额定资料、现场降额系数及来源 | 逐机组现场可用 kW、kVA、额定类别和所绑定的产品资料摘要 |
| domain-rc:generator-load-study | ratings，已定位机组的现场额定；schedule，各机组分摊的有功负荷时序和平均时窗 | 每个工况已见的最大滑动平均 kW、对应时段、证据来源和覆盖完整性 |
| domain-rc:distribution-loading | network，配电线路及端点依据；schedule，扩容前后各负荷的路径、相别及同期 kVA | 各段现状和新增 kVA、分相分布、偏差率及未决线路 |
| domain-rc:power-dispatch | network，同版配电网络；schedule，按馈线标识指定供电份额和退出对象 | 各末端实际收到、各设备和线路承载的 kW 与 kVA，以及未送达的份额 |
| domain-rc:feeder-conductors    | physical_netlist，已安装芯线的电气网表；designations，独立端子功能表                   | 各馈线具备的导体、功能冲突和标注未决的芯线                   |
| domain-rc:cable-netlist        | layout，带设备端子和馈线中心线的实施布置；terminations，独立安装芯线端接表             | 按芯线交付的电气物理网表，可追溯至安装记录及馈线图元         |
| domain-rc:chilled-water-network | scene、water_netlist，同版布置及端口级水力物理网表 | 设备清单、供回水接续、场景与网表摘要 |
| domain-rc:winter-water-protection | scene，设备与冷却水分段 USD；schedule，按冬季工况提供的措施和区间依据 | 分段对应机组、各工况温度裕量或排空结果及未决项 |
| domain-rc:water-pressure | network、schedule，选定的安装管网和项目同时流量工况 | 正常及阀门关闭工况的管段流量、压降、节点残差、末端压差及裕量 |
| domain-rc:terminal-pressure-check | study、requirements，研究及项目必验工况；可选 observations 为现场稳态读数 | 项目验收结果与退出码，可追踪模型压差、现场对照、测量不确定度及实测服务裕量 |
| domain-rc:storage-network      | scene，米制静态 USD；water_netlist，同场景的水力物理网表                               | 每条水箱至末端热传递连接及其供回水路径                       |
| domain-rc:storage-transient    | network，已提取热传递网表；inventory，水箱选型；schedule，失冷和恢复时序               | 分工况的逐段能量收支、首次供冷缺口和已确认时间范围           |
| domain-rc:lvs                  | schematic_netlist、physical_netlist                                                    | 缺接、多接、端口身份差异和无法判定项                         |
| domain-rc:rack-heat-allocation | power，逐设备运行功率表；rejection，逐设备散热分配表                                   | 同一工况下各设备的功率、空气侧与液侧等散热量、残差和缺项     |
| domain-rc:rack-heat-coupling   | federation，项目物理网表；power，逐端口输入功率；calorimetry，逐回路量热及其他散热记录 | 逐设备热量分配、已核对的安装端口、热量差额与未决观测         |

同一设备的 A、B 端口分别记录工况输入功率，备用端口以显式零值表示。每条单相液路以有向质量流量（kg/s）、定压比热（kJ/(kg·K)）及两端温度（°C）计算显热功率。房间和其他边界的散热量独立给出，因而可以发现未闭合的热量。按机柜标识及已安装端口核对各输入，未决观测保留原因。运行 `texsys build -p examples/domain-rc --target rack-heat` 可复算 40 kW 输入、32 kW 液冷、8 kW 入室的合成案例。[输入与输出契约](assets/rack-coupling.schema.json)

项目可将不同出图修订纳入同一协调基线。对照清单为每个成员给出 domain、scope、baseline，可选 netlist_digest 固定具体内容；各设备给出对照表出处、在成员中的实例 ID、要核对的端口、接口类型及是否要求已接线。来源有冲突的成员会保留未决，其余成员仍可独立核对。同一名称在不同成员中不自动建立接续。运行示例的默认构建可得到两份独立的 LVS 和一份项目物理网表。[联邦交换格式](assets/federation.schema.json) · [机柜电、水接口对照](../../examples/domain-rc/src/federation.json)

静态回水使用同一标高基准。施工资料提供各地漏位置、按排水方向排列的候选管段及排放段。提取器把上一段末端投影到下一段中心线，核对是否存在唯一接入里程。折线共享顶点对应同一里程，重叠折返导致的不同里程保留未决。先定位阀的两端并核对方向，只在该地漏实际经过的区间计入止回装置。地漏裕量为地漏标高减排放端回水标高。阀的静压水头以两个端口中较低者计算，下限为零。工况交付记录阀的可用性、额定依据和额定裕量。阀关闭后的流量、泵启动过程及集水池蓄量另行验算。交换文件使用米和同版场景摘要。[排水路径、工况与结果契约](assets/tailwater.schema.json)

端口交换格式见[JSON Schema](assets/netlist-contract.json)。USD 适配器从默认 Prim 读取 schema_version、scope、domain、baseline、frame、complete。端口 Prim 使用 rcRole=port、identity、instance 和 interface；其局部原点经过世界变换后给出配接点。路由采用一条 linear BasisCurves，并标记 rcRole=route 和 identity。每端可使用 startPort / endPort 显式端接，或使用带 start / end 前缀的 Joint、Interface、ToleranceM 声明点配接。多个候选保留为未决。[输入场景](../../examples/domain-rc/assets/hydraulic.usda)

电缆端接表采用 `cable-terminations` v1，与布置共享 domain、scope、baseline 和 frame。每条馈线的 cores 按全范围唯一芯号记录两个端子，次序与实施侧路由首末点一致。端子未知时填 null，未获得整条馈线的芯线清单时保留未决。馈线可选的 `feed_end` 为 0 或 1，供固定送电方向的工况研究使用。缺方向仍可比较无向安装接续。芯线级差异带有图元、馈线和端接表路径；并行同端接续有计数差异时列出全部候选记录。

冷冻水工况表可在 `pipe_outages` 中按名称声明退出事件。每个事件以 `base_case` 和 `base_case_digest` 选定 `cases` 中的基准工况，`unavailable_pipes` 列出同时退出的安装管段，可选的 `switching` 列出其余管段的目标开闭状态。求解沿用基准同时流量、冷源压力、开放阻力和末端最低压差。退出段按关闭边界处理；该模型适用于完成隔离后的稳态。报告可追溯基准阀位与切换依据，正反向流量由重新求解得到。项目用已有的 `required_cases` 选择所需事件，基准修订不符的事件保持未决。[管段退出事件格式](assets/water-pressure-outages.schema.json)

冷冻水现场快照按试验批次绑定完整阀位、冷源供回水压力、末端流量以及独立必测点。仪表正方向和不确定度用于比较；取压值需折算到工况采用的同一水头基准。项目验收计划定义各必测点的允许差值。项目可另在 `flow_transfers.cases` 选定切换试验、窗口及逐末端最低流量和最长缺流时间，观测文件的 `transfers` 提供切换前后所见阀位及连续区间的流量极值。时钟、误差界、计量方向、末端与记录修订随结果交付。稳态设计与切换观测可各自保留已确认的偏差。[快照与验收计划格式](assets/water-pressure-observations.schema.json)

电气端子功能表按稳定端口 ID 登记 L、N、PE、PEN、DC+ 或 DC-，来源可为端子铭牌或产品接线资料。每根芯线匹配两端的功能后归入馈线，保留两端标识、功能和安装几何引用。两端功能冲突可定位到芯线；缺少某一标注只影响使用该馈线的路径。路径上还可单独追踪 PE 后再次出现 PEN 的位置。设备内部接线与电源接地方式需另交证据，线路阻抗及保护动作需另行校核。[导体交换格式](assets/feeder-conductors.schema.json)

配电网络逐线路记录起讫设备及端点核实依据。扩容工况按设备序列给出辐射路径，要求相邻两设备之间可唯一识别馈线。计算采用项目声明的同期视在功率标量和。分相表仅计承载于三相线路的单相负荷，偏差率取各相与三相平均值之差的绝对值最大值除以平均值。相别缺失时，总量与分相的证据分别记录。分流工况直接指定馈线序列，可区分同端点的不同馈线。多路供电须给出分流依据，退出设备或线路对应的份额单列，要计入接替供电需显式声明新路径和份额。两种工况都绑定场景与坐标系，交付物记录网络和工况摘要。适用范围为给定同时系数、负荷与分配的稳态回放，功率因数、潮流、损耗和自动切换响应需要各自的模型。[配电网络、工况和观测交换格式](assets/distribution-loading.schema.json)

送风过滤路径目标读取 v1 `air-supply-network`，其中 `baseline`、`frame`、`case`、`scene_digests.building`、`scene_digests.equipment` 选定工程范围。`systems_complete` 说明系统清单完整性，各系统提供 `kind`、`complete`、`source`、`precision_air_units`、`nodes` 与 `edges`。连接可写成已开启的节点对，也可用 `from`、`to` 和 `state` 描述开启、关闭或待确认（`open`、`closed`、`unknown`）。网络为有向无环送风图。报告为每一种可达过滤状态保留一条示例路径及其启用状态，按不同初效、中效级别计数；同一等级重复串联只计一次。每个未分类装置最多可能补足一个等级。拓扑及开闭状态来自项目声明，实际流量与泄漏须另行验证。[送风过滤交换格式](assets/air-filtration.schema.json)

冬季冷却水研究读取同一实施场景的 `water-cooled-chiller` 及 `cooling-water-section`，以 `texsys:identity` 标识，各分段的字符串数组 `texsys:waterChillers` 列出关联机组，共用管段只计算一次。场景根的 `frame`、`baseline`、`hvacEnergyInventoryComplete`、`coolingWaterSectionsComplete` 确定计算边界与清单完整性。v1 `winter-water-cases` 输入以场景修订、基线、坐标系定位工况；每个 `cases` 表项提供 `season = winter`、`outdoor_design_c`（°C）、`duration_h`（h）、边界依据 `source` 及按分段索引的 `sections`。每段声明措施清单的 `complete`、出处及 `measures`。每项措施提供自工况起点计时的证据时段 `window_h`、名称 `action`、出处 `source` 和计算方法。`fluid-temperature` 使用证据时段内的 `minimum_fluid_c`、`freezing_point_c` 上下界与 `fluid_source`。`drain-down` 使用项目声明完全排空后的 `residual_volume_l` 上下界。此接口消费独立研究或试验的结果，保留其来源。[冬季工况交换格式](assets/winter-water-cases.schema.json)

气流模型从 `ClassifiedSpaces` 的正交房间识别垂直共墙。每个实施开口以一个垂直薄盒标记，`rcRole=airflow-opening`，并给出 identity、zone、normal（±x 或 ±y）和 boundaryKind（interior 或 exterior）。薄盒中心须在所指面上，矩形须完全落入该面；室内开口的另一侧从共墙识别。室外开口须显式标注。根对象给出 frame、baseline、spaceUsesComplete、airflowOpeningsComplete。仅有几何邻接的房间可以比较压差，开口记录决定模型中的空气交换。

`airflow-cases` 按工况登记机械送回排风量（m³/h）、定压区域及室外压力（Pa），以及各开口在该状态下有来源的漏风系数和指数。正流量从开口记录的第一个区域流向第二个区域。多个未知区域共同求解，每个自由压力区须通过有效路径连至定压边界；逐区残差达到容差后才交付数值结果。给定目标室外压差时固定该区压力，重新求解其余区域以得到所需净送风量。结果中的 `target_path_flows_out_m3_h` 逐开口给出该目标下的有符号流量，从当前房间外流为正。其总和等于所需净送风。下游可用 `schedule_digest` 选定工况表修订。开口面积用于核对布置，系数取自独立工况资料。[气流交换 Schema](assets/zonal-airflow.schema.json)

`room-pressure-observations` 记录建筑分区在稳态工况下的独立差压测量。每个批次给出时间及其时区、稳态确认和出处，每个读数给出高低压取压端、Pa 示值、仪表、校准依据和非负不确定度。按选定批次摘要读取记录后，以房间减参照的方向给出压差区间。一个边界缺测时，其他边界的读数仍可独立使用。[房间压差测量交换格式](assets/room-pressure-observations.schema.json)

`equipment-placement` 给出设备、机房和固定障碍的 USD 图元路径，六个面按世界坐标轴标识。整面净距沿面法向量取，横向投影有面积交叠的实体与机房边界均可成为控制对象；穿出墙面的距离保留负值。具体拆装任务还可给出面、深度、宽度及从设备底面起算的高度，在水平检修面中央生成独立作业包络。障碍清单是否完整随结果交付，已查到的碰撞可以直接定位。旋转拆装、曲线路径和非正交实体需其他几何模型。[设备净空交换格式](assets/equipment-clearances.schema.json)

`cooling-performance` 取同一型号表中包围指定温度的两个相邻性能点，对额定冷量（kW）和 COP 分别线性插值。超出温区或缺少产品资料时，逐工况、逐台标为未决。数据表和工况各有摘要。同一产品观测可被另一个项目采用，消费方需核对安装型号、选用工况与设计温度。设备实际供给还取决于运行状态、输配路径和已分配的负荷。适用范围为表中其余边界条件相同的稳态设备数据。[设备性能交换格式](assets/cooling-performance.schema.json)

供冷服务网表按设备和房间各一个集总端口建模。实施侧只读取项目选定的图元。在世界坐标中，将每条有向中心线的首端与设备包络匹配、末端与房间包络匹配，按每轴 0.000001 m 的容差登记候选对象。两端均能唯一定位时交付接续；多个候选保留为未决。原理端接表可经 `domain-rc:schematic-netlist` 转换，在同一范围和基线上做 LVS。此粒度适用于已标明用途的设备至房间直接服务线。管件端接、风阀和实际通水通风能力需要对应领域的证据。

给定运行分配时，每条路线分别标记可用、停运、端点错误或尚未核实。表中多条路线服务同一设备和房间时，用 `dispatch_routes` 指定本工况采用哪一条。每笔正分配只计入已核实、未决、未送达三项中的一项。涉及不同时刻的恢复动作应另建工况。研究可重新调配的能力时，再给出逐台同温度冷量、每间房的需求以及每条路线的容量或其无额外限制的依据。模型允许在独立路线间连续调节负荷，先对已确认路线求最大流，再加入有设计依据的未决路线求条件上限。两次求解都交付一组同时分配和相等的最小割容量，逐房分配可能有多个等价解。共用总管或泵曲线、流体平衡、控制器响应均需另行建模。[供冷服务交换格式](assets/cooling-service.schema.json)

直线路线剖面以米为单位，保存通道、门洞和障碍的世界坐标包络，允许多个设备运输任务共用一次提取。通道净宽取连续可通行的地面带宽。运输宽度还需考虑同一设备在给定高度下能否沿固定横向位置直线平移；门洞和架空障碍可成为控制位置。参考底标高取沿线通道与开口的最高底面。成果记录源场景摘要与路线标识。转弯、坡道、轮压与搬运工艺由对应模型校核。[直线剖面交换格式](assets/clearance-profile.schema.json)

蓄冷研究的 `inventory_digest` 对整份输入库存取规范化 JSON 内容摘要，每个工况的 `case_digest` 对仅保留该具名工况的整张时序表取同类摘要，涵盖公共字段、坐标系、范围及基线。可调用 `cooling_case_digest(schedule, name)` 复算。验收方可以独立选定库存和各工况修订。

蓄冷模型用内净包络及有效水位计算水量，结合体积热容（kWh/(m³·K)）、可用温差及系数得出初始可用冷量（kWh）。每一时段列出末端负荷、其他冷源实际送达功率、各箱可用放冷功率（kW）、停用管段和末端分配比例。时间从事故起点按分钟累计。模型按既定比例放冷，逐段核对能量守恒。结果的 service 计入恢复供冷，storage_only 单独计算蓄冷能力。某段缺少恢复供冷记录时，两者可有不同的已确认时长。适用范围为给定出力和可用路径的分段恒负荷工况，未建模充冷、混水温度、泵曲线或控制器切换。[蓄冷时序交换格式](assets/storage-transient.schema.json)

工况有空档时，`confirmed_through_min` 保留从事故起已连续积分到的时刻，`remaining_kwh` 给出该时刻各箱的余量。后续区间仍核对已知末端的分配比例、管段停运和放冷功率；运行出力缺失时可用选型最大放冷功率作为上界。后续证据确认不足时，`shortfall_by_min` 是首次供冷不足的最晚时刻，`shortfall_witness` 指向水箱、对应时段、输入来源和缺口依据。项目可在每个工况的 `no_charge_source` 引用覆盖整场事故及缺测时段的充冷隔离记录。此时跳过未知时段消耗，以各箱此前余量作为可用冷量上界；即使在这个上界下仍会耗尽，便可收紧缺供时刻。连续供冷的证明仍止于第一个证据缺口。

规则配置采用[判据交换格式 v1](assets/rc-conditions.schema.json)。rc.conditions 按条列出 left、relation、right 和可选 tolerance。fact 引用本次已校核来源的观测量，parameter 引用同一规则的参数。容差可设为常数，也可绑定本次量测的精度。支持 minimum、maximum、above、below、within、between、equals 和 one_of。between 使用含端点的两值区间，可以直接绑定标准规定的上下限数组。one_of 从右侧的参数列表选择同类型的值。缺观测量为无法判定，缺配置参数为输入错误。已知违例优先，on_violation 可指定无法判定，例如共路证据不足以证明物理独立。

rc.qualifiers 可声明测量依据必须满足的条件。例如，粒径门槛及静态或动态测量工况必须匹配，累计粒子浓度才可与上限比较。工况不符或缺失时该读数无法判定。已经取得适用读数，仅有部分范围未覆盖时，rc.conditions 可以同时表达峰值约束与覆盖要求。扫描中已知超限优先于范围缺失。多变量区间评估保留每个量的结论。温度测序按相邻时刻求绝对温变率，并保留采样间隔及最小表面露点裕量所在时刻。

从主仓根目录运行：

```bash
uv run --locked texsys lock -p examples/domain-rc --check
uv run --locked texsys build -p examples/domain-rc
uv run --locked texsys package test domain-rc -p examples/domain-rc
```

### UPS 恒功率放电资料

`ups-discharge-catalog` 版本 1 的 `curves` 以曲线 ID 索引。每条记录有出处 `source`、电池组配置 `configuration`、老化依据 `ageing_basis`、电池温度 `battery_temperature_c`、终止直流电压 `dc_cutoff_v` 及初始荷电状态 `initial_soc_percent`。按交流输出功率递增排列 `ac_output_points`，每点给出 `kw` 和 `minutes`。`runtime_basis` 取 `cutoff-runtime`（产品或试验记录的截止时长）或 `guaranteed-minimum`（保证的最短时长）。有依据在相邻点间使用单调包络时，以 `monotonic_source` 指明出处。

`ups-discharge-selection` 版本 1 用 `catalog_digest`、`scene_digest` 和 `frame` 绑定产品表和安装场景。每个 `ups` 条目记录图元 `prim`、选用曲线 `curve`、现场依据 `source` 及同组运行条件。消费方按设计交流负荷查表，落在两个合格点之间时可交付时长上下界。保证值只提供下界，超出曲线负荷范围时保留未决。

### 发电机额定与工况时序

`generator-rating-catalog` 版本 1 用 `scene_digest` 和 `frame` 绑定实施场景。按安装机组 ID 在 `generators` 中给出额定类别 `rating_basis`（unlimited、500h 或 other）、产品资料出处 `source`、`rated_kw`、`rated_kva`、现场条件出处 `site_source` 及各自的 `site_factor_kw`、`site_factor_kva`。限时选型可给出产品运行上限 `product_annual_limit_hours`。两种容量分别降额；有功输出还受可用视在容量约束。

`generator-load-schedule` 版本 1 用 `ratings_digest` 锁定额定交付物。每个 `cases` 条目声明 `source`、`duration_seconds`、`averaging_seconds`、`complete`，以及按时间排序的 `intervals`。每段以 `start_s`、`end_s`、`source` 和 `generator_kw` 给出分配给各机组的恒定 kW。缺失区间或机组读数时，仅在连续且有来源的时段内计算完整窗口，保留其起止秒数。项目提供平均时窗及并机分配依据。

### 储油量与并发耗油工况

`fuel-inventory` 版本 1 以 `frame`、`scene_digest` 绑定安装基线。每个 `tanks` 条目提供有效容积 `usable_liters` 及 `capacity_source`、供油机组数组 `generators` 及 `connection_source`。每台机组在所分析的工况中由一个固定油箱供油。`fuel-duty-schedule` 版本 1 以 `inventory_digest` 指定油箱资料，提供计划出处 `source`、必验工况数组 `required_cases` 和 `cases`。每个工况列出 `active_generators`、`fuel_liters_per_hour` 及耗油数据来源 `source`。耗油量按恒定工况折算，未计入途中的补油。

各油箱分别累计同一工况内已确认的运行机组耗油量。以有效容积除以该流量得到 `hours_upper_bound`，缺测机组运行时会进一步缩短供油时长。必验工况的运行机组及其耗油完整时，交付控制工况 `limiting_case` 及 `observed_hours`。报告另列在全部必验工况中均未运行的备用机组。工程判据由条款或项目选定。

### 竖向承压接触

`domain-rc:bearing-contacts` 接受米制、Z 向上的展平场景 `scene` 与 `selection`。选择文件采用 `bearing-layout` 版本 1，包含场景的 `frame`、`scene_digest`、承载设备和楼板分区的 ID 到 USD 路径映射 `assets`、`zones`，以及每个支座的路径和设备归属 `pads[id] = {prim, asset}`。选中的对象使用世界坐标下正交的实心包络。

默认模式下，每个已确认的支座须在顶部与指定设备接触、在底部完整落于唯一分区。结果记录设备、分区、水平承压面的两个世界角点和面积（m²），另列悬空、部分接触、跨区或未定位的对象。几何提取适用于选定的承压面，反力、工况、材料和结构承载限值由下游项目提供。

选择文件可指定 `contact_mode = "partitioned"`。当多个同标高分区的水平矩形接触面完整拼合支座底面时，`contacts[支座].patches` 按分区记录各自的角点和面积。提取器逐条检查底面上的矩形带，确认每处均有且仅有一个承接分区。标高接触容差为 1 µm，水平拼缝仅容许世界坐标浮点舍入。缝隙、重复覆盖及不完整接触保留为未决。各分区反力需取自同一工况的结构专业依据。


### 平壁内表面温度

`domain-rc:planar-surface-study` 接受米制场景 `scene`、版本 1 的断面资料 `sections`（`kind=planar-sections`）和工况表 `schedule`（`kind=surface-boundaries`）。断面资料用 `scene_digest`、`frame` 绑定场景。`faces` 以构件 ID 索引，每项提供房间 `room`、场景路径 `prim`、确认整块面片适用一维稳态近似的 `one_dimensional_basis`，以及材料层 `layers`。每层记录 `material`、`source`、`thickness_m` 和 `conductivity_w_mk`。实际构造层厚度取项目断面资料。

工况表以 `sections_digest` 选定断面资料的规范化 JSON 摘要。`rooms[房间][工况]` 提供 `source`、空气干球与露点 `air_c`、`dew_point_c`；`boundaries[面片]` 提供 `source`、对侧空气温度 `opposite_air_c` 与两侧表面换热热阻 `inside_film_m2k_w`、`opposite_film_m2k_w`。对侧也可给出有出处的界面温度 `opposite_surface_c`；此时传热止于该界面，省略对侧空气和表面热阻。计算将边界表面热阻与各层厚度／导热系数串联，热流向对侧为正，内表面温度等于本侧空气温度减去热流密度与本侧表面热阻之积。报告保存逐层热阻、边界、热流、内表面温度及未决面片。此模型用于具有独立适用依据的均匀平壁断面。局部热桥、土壤侧边界温度和瞬态工况需要相应专项依据。

### 全年逐时能耗

`domain-rc:annual-energy` 接受两个版本 1 的 JSON 文件。`basis`（`kind=annual-energy-basis`）用 `year` 和固定时差 `utc_offset_minutes` 确定日历年，提供 `frame`、`scene_digest`、`source`、`comparison_basis`、气象资料摘要 `weather_digest`、运行计划摘要 `operation_digest` 和计量范围 `meter_boundary`。`runs`（`kind=annual-energy-runs`）在 `rooms[房间][方案]` 给出 `basis_digest`、方案 `model_digest`、构件传热系数 `u_values_w_m2k`、计算出处 `source`、`quantity=hourly-mean-input-kw` 与 `blocks`。每个块以带 UTC 偏移的 ISO 时间 `start` 和非负小时均值序列 `mean_kw` 描述连续时段。首值覆盖从起始时刻到一小时后的区间，缺值可写 `null`。年内各块可以乱序交付。计算按绝对时刻对齐到基准年，当地时间变更需要在输入时刻中显式保留偏移。

`known_kwh` 为已覆盖、无重叠的时段能耗；`annual_kwh` 仅在全年完整时给值。平年共 8760 小时，闰年共 8784 小时。缺项和重复时段分别以从年初起算的左闭右开小时序号区间给出。物理模型、动态仿真的气象与运行输入及用能边界由出具方确认。此积分口径适用于计量范围内的非负输入功率。

### 气流通路容量

`domain-rc:airflow-capacity` 以 `scope.network` 读取版本 1 的 `airflow-capacity-network`。交付物包含 `frame`、`scene_digest`、`case`、`zone`、供风节点 `inlet`、接收节点 `delivery`，以及有向通路表 `arcs`。各通路给出 `from`、`to` 和非负容量 `capacity_m3_s`。并行通路分别计量。输出所选网络的内容摘要、最大可分配风量、各通路的一组可行流量和最小割的通路序号。成果用于复核容量约束及节点流量守恒；运行压差和风机工况由相应专业模型计算。


在电气计算模块中，`electrical.interruption_bounds(window_ms, segments, edge_error_ms)` 从负载端连续受电状态记录求最长单次断电时长范围（ms）。区间按时序输入，只接受有记录的 `powered` 和 `interrupted`；间隙保留未知。函数按每个边沿的绝对计时误差缩小已确认的状态区间，并返回上下界、各已确认时段及观测窗口起止是否已确认供电。测点归属、切换场景和产品耐受限值由消费方核对。


几何模块 `quarter_turn.overlap_angles(length, width, local_bounds, tolerance)` 计算矩形货物绕底面中心旋转四分之一圈时，与固定正交矩形重叠的角段。坐标原点为转轴，第一、第二轴分别指向运动的进向和出向，单位为米。结果按度给出临界角和可复核的内部姿态。调用方提供竖向交叠、所在层、货物包络和净空清单。由四个分离轴上的投影等式求出临界角，可识别两个整数角度之间的短碰撞。[多边形裁剪对照算例](tests/test_quarter_turn.py)

冷却水补水计算 `makeup_endurance` 接受各水箱的有效容积（m³）、各入口的同时需求（m³/h）及有向支路的能力（m³/h）。在市政补水中断、阀位与需求恒定的工况下，以管网流量分配核算所有入口能同时得到所需补水的最长时间。输出含各弧累计输水量及限制时长的割集；可用不同的支路能力假设分别计算时间下界和上界。[领域算法](src/texsys_domain_rc/makeup_reserve.py) · [独立割集与水量守恒校验](tests/test_makeup_reserve.py)

同一网络可用 `makeup_shortfall` 计算给定时长（h）内的累计需求、最大供水量、系统缺水量和限制供水的割集。逐入口缺水区间的两个端点分别来自优先供应该入口和优先供应其他入口的最大总量分配。各入口的上界不能相加；运行人员的调度顺序需由项目另行给出。

`first_flow_deficit` 按连续净入流的区间极值、流量误差和时基误差，给出从断水开始可确认的连续供水时长及首次缺流的最晚时刻。只有极值所在区间能完全落入核验窗口时，单个低谷才可用于举证；若可确认整段均低于需求，则采用与核验窗口相交的确定缺流区间。[时间界限验收](tests/test_first_flow_deficit.py)

项目端口核对可运行 `texsys build -p examples/domain-rc --target project-lvs`。清单复用联邦的设备、专业编号、端口和修订选择。成员的 `lvs_basis` 记录独立的设计与实施接续资料，`schematic_digest` 与 `netlist_digest` 可分别固定交付版本。由项目声明 `lvs_inventory_complete` 并为每个选定成员列出端口后，报告才计算比例。同一专业、范围和修订下的同一端口只能列一次。独立性由项目根据实际资料确认，工具可识别同源声明及交付物中可见的相同接续源摘要。`conclusive_fraction` 计入一致和确认差异，`matched_fraction` 只计一致。部分网表中的已知错接仍可举证；端口全部接续尚无完整清单时，其余端口保持未决。未列入范围的端口差异可在成员的完整 LVS 结果中查阅。[清单样例](../../examples/domain-rc/src/federation.json) · [报告格式](assets/project-lvs.schema.json)

管段露点观测的时刻以带时区的 `time_origin` 为原点，以秒计。项目为同一管段和工况指定有校准依据的表面温度与空气露点通道，固定该次记录摘要。每个读数给出整个时段内成立的温度区间。计算按通道各自的最大计时误差收缩时段，求共同覆盖，再按两个温度区间求温差上下界。离散读数之间的空档保留在 `gaps_s`。报告保留管段位置、测点、校准、工况选择、时间原点与资料摘要，供条款检查逐时段判断。[测点计划、观测及成果格式](assets/dew-history.schema.json) · [区间运算及回放](tests/test_dew_history.py)

竖直矩形窗洞可调用 `texsys_domain_rc.sunlight.opening_exposure` 计算单一太阳位置下的直射可见面积。输入为窗面世界轴与朝向、窗洞横向及高度范围、指向太阳的向量，以及有标识的正交遮挡体包络和阻光属性。计算会裁去构件位于窗面室内一侧的部分，在窗洞坐标系合并投影，报告每个投影多边形及可见面积上下界。调用方负责工况选择、玻璃直射特性和外部遮挡清单完整性。[几何反例](tests/test_sunlight.py)

整窗气密性可调用 `texsys_domain_rc.air_permeability.check_permeability` 核对指定压差下的流量记录。计算先比对总流量和夹具本底试验的压力区间、配对容差及空气体积换算基准，再求净流量上下界和单位面积、单位开启缝长的空气渗透量。项目提供选定工况及限值，整窗样本识别、等级证据和尺寸适用性由调用方核对。[流量及压力反例](tests/test_air_permeability.py)
