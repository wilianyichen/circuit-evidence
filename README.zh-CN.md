# Circuit Evidence · 电路仿真验收

**AI 交来的电路，具体通过了哪几项检查？**

把电路连接、题目要求和检查条件交给 Circuit Evidence。它在 Windows 上调用 LTspice，把每条要求对应的测量值、通过或失败的结论，以及原始仿真文件一起交回来。你可以用命令行复现，也可以让后台 Agent 通过本地 MCP 调用。

[English](README.md) · [快速开始](#快速开始) · [接入 Agent](#接入-agent) · [v0.1.0 发布页](https://github.com/wilianyichen/circuit-evidence/releases/tag/v0.1.0)

## 实际仿真发现两条支路接反了

三端电阻黑盒里，交换 B、C 两条支路后，B–C 的读数依然正确。把三个端口组合都测一遍，就能看出问题出在哪里。

| 端口 | 题目要求 | 反例测得 | 检查结果 |
| :--- | ---: | ---: | :--- |
| A–B | 1.50 Ω | 2.50 Ω | 超过上限 |
| B–C | 3.00 Ω | 3.00 Ω | 通过 |
| A–C | 2.50 Ω | 1.50 Ω | 低于下限 |

这是 LTspice 26.1.1 的运行结果。测试时让第三端开路、注入 1 mA，由模拟电压换算阻值。报告会指出 `ab_hi` 和 `ac_lo` 两项失败，并把「使用五个 1 Ω 电阻」这条要求标为待复核。[案例定义](examples/resistor-blackbox/case.json)

## 快速开始

安装 Python 3.12 和 Windows 版 [LTspice](https://www.analog.com/cn/resources/design-tools-and-calculators/ltspice-simulator.html)。在仓库目录打开 PowerShell，按本机安装位置修改 LTspice 路径。

```powershell
py -3.12 -m venv .venv
$python = ".\.venv\Scripts\python.exe"
& $python -m pip install -r requirements.txt
$ltspice = "$env:LOCALAPPDATA\Programs\ADI\LTspice\LTspice.exe"
& $python run_evidence.py --ltspice $ltspice --case resistor-blackbox --variant negative
```

命令会给出 `evidence.json` 的路径。这个反例的退出码为 0，表示**成功复现了预期的两项失败**。去掉 `--case` 和 `--variant`，即可运行全部四组回归。

| 内置案例 | 正例 | 故意引入的错误 |
| :--- | :--- | :--- |
| [三端电阻黑盒](examples/resistor-blackbox/) | 6/6 项通过 | 交换两条支路，2 项失败 |
| [差分电机驱动](examples/motor-drive/) | 25/25 项通过 | 反馈电阻从 10 kΩ 改为 20 kΩ，8 项失败 |

## 接入 Agent

```powershell
& $python -m pip install -r requirements-mcp.txt
& $python smoke_mcp.py $ltspice ./mcp-smoke-runs
```

这条测试会通过 stdio 实际调用 MCP，并验证自定义分压器的输出为 **2.000 V**。

<details>
<summary>展开本地 MCP 配置</summary>

如果客户端使用 `mcpServers`，把下面的示例绝对路径换成本机路径。

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

接通后，可以把这句话交给 Agent。「跑一下三端电阻黑盒的反例，告诉我哪两组端口出错，并给出证据文件。」

- `run_circuit_example(case_id, variant)` 重跑内置正例或反例。
- `verify_circuit_design(source_text, requirements, elements, analysis, measurements, checks)` 接收自定义电路和检查条件。可以从[实际跑过的分压器请求](smoke_mcp.py)改起。

## 报告能证明什么

打开 `evidence.json`，从题目要求追到对应的检查、阈值和测量值。每次运行还会保存提交的需求文本 `requirements.txt`、检查声明 `contract.json`、实际执行的 `circuit.cir`、原始波形 `circuit.raw` 和 LTspice 日志 `circuit.log`。

当前支持电阻、直流电流源、电压源（直流或分段线性）和线性电压控制电压源的瞬态检查。题意是否理解到位、检查是否覆盖整道题、原理图连接和实物性能，都可以再单独核验。

两个案例源自 MIT OpenCourseWare，使用理想模型并作为**回归测试**。电机例以线性受控源表示运放。[电机驱动原题](https://ocw.mit.edu/courses/6-01sc-introduction-to-electrical-engineering-and-computer-science-i-spring-2011/56e33ac20f7bffe456a08f307b9eb6b9_MIT6_01SCS11_mid02_review.pdf#page=13) · [电阻黑盒原题，第 1 次作业第 1-3 题](https://ocw.mit.edu/courses/6-002-circuits-and-electronics-spring-2007/pages/assignments/)

项目复用本机 LTspice、用于读取波形的 [spicelib](https://pypi.org/project/spicelib/1.5.1/) 和 [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)。源码采用 [GPL-3.0-only](LICENSE)。
