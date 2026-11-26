"""OCP (ORv3 / ACS Liquid Cooling / DCF) executable standards capability package."""

from __future__ import annotations

from pathlib import Path

from texsys.evidence import write_json
from texsys.formal import Diagnostic
from texsys.packages import TexsysPackage
from texsys.targets import Artifact, BuildContext, TargetDefinition, TargetResult

from .evaluator import RULES_DIR, evaluate_project_ocp_compliance, load_ruleset


def _render_markdown(report: dict) -> str:
  lines = [
    "# OCP 标准合规校核报告 (`ocp-standards`)",
    "",
    f"- **判定状态**：`{report['status']}`",
    f"- **规则集摘要**：`{report['ruleset_digest']}`",
    f"- **统计**：pass `{report['counts']['pass']}` / fail `{report['counts']['fail']}` / indeterminate `{report['counts']['indeterminate']}`",
    "",
    "## 校核明细",
    "",
    "| 条款编号 | 状态 | 对象 | 说明 |",
    "| :--- | :--- | :--- | :--- |",
  ]
  for item in report["findings"]:
    obj = item["object"] or "-"
    lines.append(f"| `{item['rule_id']}` | `{item['status']}` | `{obj}` | {item['message']} |")
  lines.append("")
  return "\n".join(lines)


def _build_compliance_report(context: BuildContext) -> TargetResult:
  report = evaluate_project_ocp_compliance(context.root)
  out_dir = context.build_path / "ocp"
  out_dir.mkdir(parents=True, exist_ok=True)
  json_path = out_dir / "compliance-report.json"
  md_path = out_dir / "compliance-report.md"
  write_json(json_path, report)
  md_path.write_text(_render_markdown(report), encoding="utf-8")

  diags = tuple(
    {
      "rule": f["rule_id"],
      "status": f["status"],
      "file": f["file"],
      "object": f["object"],
      "message": f["message"],
    }
    for f in report["findings"]
    if f["status"] in {"fail", "indeterminate"}
  )
  return TargetResult(
    status=report["status"],
    artifacts=(
      Artifact("ocp-compliance-json", "build/ocp/compliance-report.json"),
      Artifact("ocp-compliance-md", "build/ocp/compliance-report.md"),
    ),
    diagnostics=diags,
    details={"counts": report["counts"], "ruleset_digest": report["ruleset_digest"]},
  )


class OcpStandardsPackage(TexsysPackage):
  name = "ocp-standards"
  version = "0.1.0"

  def check(self, root: Path) -> tuple[Diagnostic, ...]:
    report = evaluate_project_ocp_compliance(root)
    return tuple(
      Diagnostic(
        rule=item["rule_id"],
        status=item["status"],
        file=item["file"],
        message=f"[{item['clause']}] {item['message']}",
        object=item.get("object"),
      )
      for item in report["findings"]
      if item["status"] in {"fail", "indeterminate"}
    )

  def targets(self) -> tuple[TargetDefinition, ...]:
    return (
      TargetDefinition(
        id="ocp:compliance-report",
        package_name=self.name,
        package_version=self.version,
        builder=_build_compliance_report,
        input_patterns=("src/**", "texsys.toml", "texsys.lock"),
      ),
    )


package = OcpStandardsPackage()

__all__ = [
  "OcpStandardsPackage",
  "RULES_DIR",
  "evaluate_project_ocp_compliance",
  "load_ruleset",
  "package",
]
