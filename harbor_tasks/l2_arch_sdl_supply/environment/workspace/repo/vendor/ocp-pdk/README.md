# `ocp-pdk`：OCP 开放计算标准多视图 PDK 单元库

本能力包将 **OCP（Open Compute Project）** 公开标准中的机柜机械、直流供配电、板级直接液冷（ACS Cold Plate / CDU）及模块化设施（DCF）固化为 **12 个多视图标准单元（Multi-View PDK）**，作为 TexSys 中与特定厂家解耦的标准参考族底座。

## 标准化端口语义（`port.kind`）

- 外部设施接口沿用通用端口：`ac-power`、`tcs`、`fws`、`room-air`、`signal`、`control-signal`、`ethernet-100g-oob`。
- 机柜内部与 OCP 盲插接口采用强类型端口：`dc-48v-busbar`、`tcs-bmqc`、`rack-mount-ou`、`ethernet-400g-plane`。

## 标准单元清单（12 族）

| 模块目录 | 标准单元名称 | 依据 OCP 规范 |
| :--- | :--- | :--- |
| `orv3-frame-48ou` | OCP ORv3 标准机柜框架 (21" / 48OU) | OCP Open Rack v3 Base Spec Rev 1.0 |
| `orv3-hpr-frame-48ou` | OCP ORv3 HPR 高密液冷机柜框架 (48OU) | OCP Open Rack v3 HPR Spec Rev 1.0 |
| `orv3-busbar-48v-hpr` | OCP ORv3 HPR 48V/50V 盲插直流母排 (3000A) | OCP ORv3 HPR Busbar Spec Rev 1.0 |
| `orv3-power-shelf-33kw` | OCP ORv3 33 kW 电源框 (6×5.5 kW PSU) | OCP ORv3 Power Shelf Spec Rev 1.0 |
| `orv3-bbu-shelf-15kw` | OCP ORv3 机柜级 BBU 备电框 (15 kW) | OCP ORv3 BBU Spec Rev 1.0 |
| `orv3-rack-manifold-bmqc` | OCP ACS 机柜液冷盲插歧管 (DN32 / BMQC) | OCP ACS Rack Manifold Spec Rev 1.1 |
| `ocp-uqd-bmqc-coupler` | OCP UQD04 / BMQC 无滴漏盲插快接头对 | OCP UQD / BMQC Spec Rev 2.0 |
| `ocp-compute-tray-1ou-lc` | OCP ORv3 1OU 液冷算力托盘 (6.5 kW) | OCP ORv3 1OU LC Tray Reference Rev 1.0 |
| `ocp-orv3-liquid-rack-assembly` | OCP ORv3 HPR 液冷整机柜装配体 (复合单元) | OCP ORv3 HPR + ACS Composite |
| `ocp-cdu-inrow-1mw` | OCP ACS 1 MW 列间液-液 CDU | OCP ACS Liquid-to-Liquid CDU Spec Rev 1.0 |
| `ocp-busway-tap-ac` | OCP DCF 列顶高密交流母线槽段 (1600A) | OCP DCF Overhead Busway Reference Rev 1.0 |
| `ocp-dcf-modular-it-pod` | OCP DCF 液冷模块化 IT Pod (复合单元) | OCP DCF Modular IT Pod Reference Rev 1.0 |

## 校验与检视

```bash
uv run --locked texsys check -p packages/ocp-pdk
uv run --locked texsys sysda pdk-inspect packages/ocp-pdk/src/library/modules/ocp-orv3-liquid-rack-assembly --json
```

## 适用边界

- 所有多维 `.lib` 工况表均标注 `state = "calibrated-reference"` 与 OCP 公开规范版本；超出标定包络时返回 `indeterminate`，禁止静默线性外推。
- 本库用于可研/方案级参考装配、端口契约约束及存量库底座重构，不替代中标厂商施工图或现场试验验收。
