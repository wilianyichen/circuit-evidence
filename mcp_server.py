"""Local stdio MCP tools for circuit evidence."""
from hashlib import sha256
import os
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from run_evidence import ROOT, run, run_example

mcp = FastMCP('circuit-evidence')


def config():
    return (Path(os.environ['CIRCUIT_EVIDENCE_LTSPICE']),
            Path(os.environ.get('CIRCUIT_EVIDENCE_OUTPUT', str(ROOT / 'runs'))))


def response(result):
    return {key: result[key] for key in (
        'evidence_file', 'variant', 'summary', 'failed_check_ids', 'requirements', 'measurements', 'limits'
    ) + (('regression_passed',) if 'regression_passed' in result else ())}


@mcp.tool(structured_output=True)
def run_circuit_example(
    case_id: Literal['motor-drive', 'resistor-blackbox'],
    variant: Literal['positive', 'negative'] = 'positive',
) -> dict[str, Any]:
    """用 LTspice 重跑一份内置电路，返回检查结论、证据路径和回归结果。"""
    executable, output = config()
    return response(run_example(case_id, variant, executable, output))


@mcp.tool(structured_output=True)
def verify_circuit_design(
    source_text: str,
    requirements: list[dict],
    elements: list[dict],
    analysis: dict,
    measurements: list[dict],
    checks: list[dict],
) -> dict[str, Any]:
    """按 README 中的结构验证一份自定义电路。支持 R、V、I、E 和瞬态电压。需求解释、测试条件、模型适用性由调用者声明。"""
    if not 1 <= len(source_text) <= 10000 or not 1 <= len(requirements) <= 30 or not 1 <= len(measurements) <= 100:
        raise ValueError('invalid source, requirement count, or measurement count')
    executable, output = config()
    case = {
        'source': {'kind': 'caller_supplied_text', 'sha256': sha256(source_text.encode('utf-8')).hexdigest()},
        'analysis': analysis, 'measurements': measurements, 'checks': checks, 'requirements': requirements,
        'variants': {'positive': {'elements': elements}},
    }
    return response(run(case, source_text, 'positive', executable, output / 'custom'))


if __name__ == '__main__':
    mcp.run(transport='stdio')
