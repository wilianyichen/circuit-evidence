# Circuit Evidence

**Which checks did your AI-designed circuit actually pass?**

Circuit Evidence runs an agent’s circuit in LTspice and gives you a report you can inspect, with each declared requirement linked to its checks, measurements, and original simulation files. Use the CLI on Windows or connect an agent through local MCP.

[简体中文](README.zh-CN.md) · [Quick start](#quick-start) · [Connect an agent](#connect-an-agent) · [v0.1.0 release](https://github.com/wilianyichen/circuit-evidence/releases/tag/v0.1.0)

## A real run with two swapped branches

The bundled resistor black box has three terminal pairs. Swap the B and C branches and the B–C reading still looks right. Checking all three pairs exposes the error.

| Terminals | Required | Faulty circuit | Result |
| :--- | ---: | ---: | :--- |
| A–B | 1.50 Ω | 2.50 Ω | Fails upper bound |
| B–C | 3.00 Ω | 3.00 Ω | Passes both bounds |
| A–C | 2.50 Ω | 1.50 Ω | Fails lower bound |

These values come from an LTspice 26.1.1 run. The test injects 1 mA, leaves the third terminal open, and checks the resulting voltage. The report names the two failed checks, `ab_hi` and `ac_lo`, and flags the separate five-resistor requirement for review. [Case definition](examples/resistor-blackbox/case.json)

## Quick start

Install Python 3.12 and [LTspice for Windows](https://www.analog.com/en/resources/design-tools-and-calculators/ltspice-simulator.html). Open PowerShell in the repository and adjust the LTspice path if needed.

```powershell
py -3.12 -m venv .venv
$python = ".\.venv\Scripts\python.exe"
& $python -m pip install -r requirements.txt
$ltspice = "$env:LOCALAPPDATA\Programs\ADI\LTspice\LTspice.exe"
& $python run_evidence.py --ltspice $ltspice --case resistor-blackbox --variant negative
```

The command prints the path to `evidence.json`. A zero exit code means the example produced the two expected failures. To run both designs and both variants, omit `--case` and `--variant`.

| Bundled case | Correct circuit | Deliberate fault |
| :--- | :--- | :--- |
| [Resistor black box](examples/resistor-blackbox/) | 6 of 6 checks pass | Swap two branches. Two checks fail |
| [Differential motor drive](examples/motor-drive/) | 25 of 25 checks pass | Change a 10 kΩ feedback resistor to 20 kΩ. Eight checks fail |

## Connect an agent

```powershell
& $python -m pip install -r requirements-mcp.txt
& $python smoke_mcp.py $ltspice ./mcp-smoke-runs
```

The smoke test calls the server over stdio and checks a custom divider with a **2.000 V** output.

<details>
<summary>Local MCP configuration</summary>

For clients that use an `mcpServers` object, replace the sample absolute paths with yours.

```json
{
  "mcpServers": {
    "circuit-evidence": {
      "command": "C:/path/circuit-evidence/.venv/Scripts/python.exe",
      "args": ["C:/path/circuit-evidence/mcp_server.py"],
      "env": {
        "CIRCUIT_EVIDENCE_LTSPICE": "C:/path/LTspice.exe",
        "CIRCUIT_EVIDENCE_OUTPUT": "C:/path/circuit-evidence/runs"
      }
    }
  }
}
```

</details>

Try asking your agent “Run the faulty resistor black box, tell me which terminal pairs fail, and show me the evidence file.”

- `run_circuit_example(case_id, variant)` reruns a bundled design.
- `verify_circuit_design(source_text, requirements, elements, analysis, measurements, checks)` accepts a structured circuit and test. Start with the [working divider request](smoke_mcp.py).

## What the report proves

Open `evidence.json` to trace requirements to checks and see the measured values, thresholds, and file hashes. Each run also saves `requirements.txt`, `contract.json`, the exact `circuit.cir`, the original `circuit.raw`, and `circuit.log`.

The current version runs transient checks on resistors, DC current sources, DC or piecewise-linear voltage sources, and linear voltage-controlled voltage sources. Judging requirement coverage, checking an editable schematic, and validating hardware are separate engineering steps.

The examples are **regression fixtures** based on MIT OpenCourseWare exercises. They use ideal models, including linear controlled sources in the motor-drive example. See the [original motor-drive exercise](https://ocw.mit.edu/courses/6-01sc-introduction-to-electrical-engineering-and-computer-science-i-spring-2011/56e33ac20f7bffe456a08f307b9eb6b9_MIT6_01SCS11_mid02_review.pdf#page=13) and the [resistor exercise, assignment 1 problem 1-3](https://ocw.mit.edu/courses/6-002-circuits-and-electronics-spring-2007/pages/assignments/).

Circuit Evidence uses a local LTspice installation, [spicelib](https://pypi.org/project/spicelib/1.5.1/) for RAW reads, and the [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk). Source code is licensed under [GPL-3.0-only](LICENSE).
