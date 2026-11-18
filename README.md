# Circuit Evidence

[简体中文使用说明](README.zh-CN.md)

A small Windows LTspice workflow for checking an agent-supplied circuit against declared requirements. The tool retains each requirement and its linked checks, the exact SPICE deck, RAW data, simulator log and check decisions. An agent can call it through a local stdio MCP server.

## Quick start

Install Python 3.12 and [LTspice](https://www.analog.com/en/resources/design-tools-and-calculators/ltspice-simulator.html). From the repository root in PowerShell, set `$ltspice` to your installed executable.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-mcp.txt
$ltspice = "$env:LOCALAPPDATA\Programs\ADI\LTspice\LTspice.exe"
.\.venv\Scripts\python.exe run_evidence.py --ltspice $ltspice
.\.venv\Scripts\python.exe smoke_mcp.py $ltspice ./mcp-smoke-runs
```

The motor-drive and resistor-black-box examples each include a positive and a deliberately faulty variant. A successful regression run detects the expected failures in the faulty variants. The stdio smoke test submits a separate voltage divider and checks its 2 V result.

## Agent tools

- `run_circuit_example(case_id, variant)` runs a bundled case.
- `verify_circuit_design(...)` checks a custom circuit supplied as structured data. See [the divider request](smoke_mcp.py) and [the stdio configuration](README.zh-CN.md#后台-agent-接入).

The supported primitives are resistors, DC current sources, DC or PWL voltage sources, and linear voltage-controlled voltage sources. Checks use saved transient voltages and derived values. The tool uses the local LTspice installation, [spicelib](https://pypi.org/project/spicelib/1.5.1/) for RAW reads, and the [official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk).

The results cover the declared checks under the supplied model. Review the requirement interpretation, check coverage, and any hardware acceptance separately. See the Chinese guide for exercise attribution and example limits.

## License

The source code is licensed under GPL-3.0-only. See [LICENSE](LICENSE).
