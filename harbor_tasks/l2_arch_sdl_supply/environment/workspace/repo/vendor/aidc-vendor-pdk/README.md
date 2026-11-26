# `aidc-vendor-pdk`：基于厂商公开资料标定的 AIDC 全链路多视图 PDK 标准单元库

本能力包落实 [ADR-0039](../../docs/adr/0039-industrial-complex-sysda-paradigm-and-short-term-aidc-focus.md) 的近期聚焦策略，依据各厂商公开发布的参考架构、产品目录、工程指南与能源认证数据（严格遵守公开资料使用边界，不纳入受保密限制的闭源源码或私有选型软件逆向数据），建成覆盖 **“中压备电 → 干式变 → UPS → 母线槽 → 液冷超节点与 AI 交换机 → CDU → 磁悬浮冷机 → 变频水泵 → 闭式冷却塔”** 全链路的 **12 个**多视图标准单元（`calibrated-reference`）。

## 厂商公开资料标准单元清单（12 个）

### 一、 算力与高速网络层（IT / Interconnect）

| 模块目录 | 设备 / 宏单元名称 | 公开资料出处 | 关键标定参数 |
| :--- | :--- | :--- | :--- |
| `nvidia-gb300-nvl72-rack` | NVIDIA GB300 NVL72 液冷超节点整机柜（1 SU） | `NVIDIA NVL72 AI Factory Enterprise RA`（2026-03）公开参考架构、`DGX GB` 用户指南及 OEM 公开直冷选型表 | 600×1068×2495 mm，1,497 kg，标称 142 kW（EDPp 155 kW / 母排建议 192 kW），90% 液冷 / 10% 风冷，25–45 °C 供液 59–177 L/min 与 15.86–126.86 kPa 压降曲线 |
| `nvidia-sn5610-switch` | NVIDIA Spectrum-4 SN5610 64口 800GbE 交换机 | NVIDIA SN5610 公开硬件手册与 Enterprise RA（2026-03） | 2U（438×775×88 mm），24.5 kg，64×800G OSFP（128×400G breakout），无源典型 920 W、满插有源光模块 1.944 kW |
| `nvidia-sn2201-oob-switch` | NVIDIA Spectrum SN2201 48口 1GbE 带外交换机 | NVIDIA SN2201 公开硬件手册与 Enterprise RA（2026-03） | 1U（428×432×43.9 mm），7.41 kg，48×1GbE + 4×100G，94–100 W ATIS，1+1 冗余电源 |
| `nvidia-gb300-dual-su-pod` | NVIDIA GB300 NVL72 双机柜算力宏单元 Pod | NVIDIA Enterprise RA（2026-03）§2 Racks 144 GPUs | 2× GB300 NVL72 + 10× SN5610 + 2× SN2201（144 GPUs，34 条双平面 SDL 拓扑连接，约 298.5 kW） |

### 二、 液冷与冷源层（TCS / FWS）

| 模块目录 | 设备名称 | 公开资料出处 | 关键标定参数 |
| :--- | :--- | :--- | :--- |
| `vertiv-liebert-xdu1350-cdu` | Vertiv Liebert XDU 1350 液-液 CDU | Vertiv Liebert XDU 1350 公开规格书与 360AI 参考设计 | 900×1243×2069 mm，干重 650 kg，DN100（4-inch）接口，1,368 kW @ 4.0 K ATD，N+1 双泵 1,200 L/min @ 244 kPa（上限 13.7 kW） |
| `york-yz-600rt-chiller` | YORK YZ 磁悬浮变频离心式冷水机组（600 RT） | 约克 `YORK YZ` 公开工程指南与 `AHRI 550/590` 性能区间 | 3900×2050×2550 mm，6,300/7,100 kg，2,110 kW，R-1233zd(E)（GWP≈1），抽管净距 3.9 m，三维 `(load, wet_bulb, chw_supply)` COP `.lib` 曲面 |
| `bac-fxv-1218-cooling-tower` | BAC FXV-1218 闭式冷却塔（单格 1,400 kW 级） | `BAC FXV` 公开选型手册（18×12 ft、8 英寸接口）与 `CTI STD-201` 认证标准 | 5490×3660×3850 mm，干/湿重 6,100/10,800 kg，22.4 kW 三风机变频立方律、湿球迫近度与蒸发补水 `.lib` 表 |
| `grundfos-nk150-250-pump` | Grundfos NK 150-250/242 变频端吸离心水泵 | Grundfos NK 150-250/242 1450 rpm 50 Hz 公开规格（EN 733 / ISO 5199） | 1550×650×820 mm，355 kg，DN200 进 / DN150 出，22 kW 4 极，350 m³/h @ 15.0 m BEP 相似律 `(flow, speed)` H-Q-η-P2 `.lib` 表 |

### 三、 供配电与备电层（MV / LV / Standby）

| 模块目录 | 设备名称 | 公开资料出处 | 关键标定参数 |
| :--- | :--- | :--- | :--- |
| `schneider-galaxy-vl-500kw-ups` | Schneider Electric Galaxy VL 500 kW 模块化 UPS | Schneider Electric Galaxy VL 公开规格书 & ENERGY STAR 认证数据 | 850×925×1970 mm，778 kg，Live Swap，双变换认证效率 96.3/97.1/97.2/97.2%、eConversion 98.9–99.5% |
| `schneider-trihal-2500kva-transformer` | Schneider Electric Trihal 2500 kVA 浇注式干式变压器 | Schneider Electric Trihal 目录 & EU Regulation 2019/1783（EcoDesign Tier 2, IEC 60076-11） | IP31 2550×1500×2750 mm，6,200 kg，Dyn11，uk=6%，Tier 2 法定上限 P0=2,790 W / Pk(120 °C)=19,000 W 精确解析 `.lib` 表 |
| `schneider-canalis-ktc1600-busway` | Schneider Electric Canalis KTC 1600A 铜导体母线槽 | Schneider Electric Canalis KTC 技术目录（DEBU024EN, 3L+N+PE） | 3000×244×164 mm（3 m 段），35 kg/m，R1(35 °C)=0.029 / X1=0.015 mΩ/m，Icw(1s)=65 kA / Ipk=143 kA，单位米压降与焦耳损耗 `.lib` 表 |
| `cummins-c2750d5-genset` | Cummins C2750 D5 备用柴油发电机组（50 Hz） | Cummins Power Generation C2750 D5 50 Hz 公开规格书 | 开架 5670×2305×2708 mm，干/湿重 18,549/19,145 kg，备用 2,750 kVA / 2,200 kW（QSK78-G9），25–100% 油耗 163/284/404/524 L/h |

## 与 `ocp-pdk` 的继承与定制边界

- **基于 `@ocp-pdk` 重建的单元**：`nvidia-gb300-nvl72-rack`（复合组合 `@ocp-pdk` 的 ORv3 HPR 机框、48V 母排、8×33 kW 电源框、BMQC 液冷歧管与 18×1OU 液冷托盘；NVLink 9× 交换托盘保留定制）、`nvidia-gb300-dual-su-pod`（经由机柜继承 OCP 底座）、`vertiv-liebert-xdu1350-cdu`（继承 `ocp-cdu-inrow-1mw`）、`schneider-canalis-ktc1600-busway`（继承 `ocp-busway-tap-ac`）。
- **保持厂商定制的单元**：非 OCP 机柜级规范的中压/冷源/交换器件（`york-yz-600rt-chiller`、`bac-fxv-1218-cooling-tower`、`grundfos-nk150-250-pump`、`schneider-galaxy-vl-500kw-ups`、`schneider-trihal-2500kva-transformer`、`cummins-c2750d5-genset`、`nvidia-sn5610-switch`、`nvidia-sn2201-oob-switch`）。

## 校验与检视入口

```bash
uv run --locked texsys check -p packages/aidc-vendor-pdk
uv run --locked texsys sysda pdk-inspect packages/aidc-vendor-pdk/src/library/modules/york-yz-600rt-chiller
uv run --locked texsys sysda pdk-inspect packages/aidc-vendor-pdk/src/library/modules/schneider-galaxy-vl-500kw-ups
uv run --locked texsys sysda pdk-inspect packages/aidc-vendor-pdk/src/library/modules/schneider-trihal-2500kva-transformer
uv run --locked texsys sysda pdk-inspect packages/aidc-vendor-pdk/src/library/modules/schneider-canalis-ktc1600-busway
uv run --locked texsys sysda pdk-inspect packages/aidc-vendor-pdk/src/library/modules/cummins-c2750d5-genset
```

## 适用边界

- 所有多维 `.lib` 性能表均标注 `state = "calibrated-reference"` 与不确定度包络；查询超出厂商公开温度、功率因数或负载范围时默认返回 `indeterminate`，禁止静默外推。
- 本库参数取自厂商公开资料与公开国际标准（AHRI 550/590、ENERGY STAR、EU 2019/1783、IEC 60076-11），不替代中标厂商项目选型单、施工图复核或现场实测验收。
