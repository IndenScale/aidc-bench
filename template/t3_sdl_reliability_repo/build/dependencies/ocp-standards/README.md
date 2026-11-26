# `ocp-standards`：OCP 可执行规范库与合规校核规则包

本能力包将 **OCP（Open Compute Project）** 核心工程约束数字化为带条款编号与定量限值的可执行规则集，与国标 `texsys-gb50174-2017` 并行接入消费工程。

## 规则域覆盖（17 条可执行规则）

1. **ORv3 机械与净距（`orv3_rack_mechanical`）**：`OCP-ORV3-MECH-001..004`（600 mm 宽、21 英寸 / 48 mm OU 模数、1600/1800 kg 静载与楼板荷载、前后 1.2 m 与顶部 0.6 m 净距）。
2. **ORv3 电源框与直流母排（`orv3_power_shelf_busbar`）**：`OCP-ORV3-PWR-001..004`（48–51 V DC 母排窗口、电源框 N+1 冗余、母线压降 ≤ 2.5%、BBU 续航 ≥ 90 s）。
3. **OCP ACS 直接液冷（`acs_liquid_cooling`）**：`OCP-LC-THM-001..002`、`OCP-LC-HYD-001..002`、`OCP-LC-CDU-001..002`（25–45 °C 供液温度包络、液冷热分配闭合、≤ 240 kPa 压降、UQD/BMQC ≤ 450 kPa(g) 动压、CDU 端温差 ≤ 5 K 与 N+1 容量、工质与漏液联锁）。
4. **OCP DCF 互操作与来源治理（`dcf_facility_readiness`）**：`OCP-DCF-001..003`（衍生厂商单元对 `@ocp-pdk` 的端口签名兼容性、PUE 目标 ≤ 1.35、缺失依据返回 `indeterminate`）。

## 使用入口

```bash
uv run --locked texsys check -p examples/nvidia-gb300-ai-factory
uv run --locked texsys build --target ocp:compliance-report -p examples/nvidia-gb300-ai-factory
```
