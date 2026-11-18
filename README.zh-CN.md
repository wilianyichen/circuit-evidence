# 电路需求与仿真证据

这个小仓库让后台 Agent 提交**电路连接、题目文字和验收条件**，用本机 LTspice 跑一次仿真，再拿回每项测量、通过或失败的检查，以及可复查的证据文件。

可以直接问 Agent：「跑一下三端电阻黑盒的反例，告诉我哪些端口不符合，打开证据文件。」后台工具会提交 `{"case_id":"resistor-blackbox","variant":"negative"}`。

| 示例 | 正例 | 反例 |
|---|---|---|
| 双端电机驱动 | 两端输出在理想模型中实现所需差分 | 反馈电阻 10 kΩ 改成 20 kΩ。中点仍正确，8 项检查失败 |
| 三端电阻黑盒 | 三组端口测得 1.5、3.0、2.5 Ω | 交换 B、C 支路。B–C 仍正确，另外两组各有一项检查失败 |

来源为 MIT 6.01SC [复习题 13–14](https://ocw.mit.edu/courses/6-01sc-introduction-to-electrical-engineering-and-computer-science-i-spring-2011/56e33ac20f7bffe456a08f307b9eb6b9_MIT6_01SCS11_mid02_review.pdf#page=13) 与 MIT 6.002 [第 1 次作业第 1-3 题](https://ocw.mit.edu/courses/6-002-circuits-and-electronics-spring-2007/pages/assignments/)。`requirements.txt` 是我们整理的文字，原题请查看课程链接。两道题采用理想元件。电机例的运放由线性受控源表示，无法验证实际供电摆幅、输出电流或电机动态。题目由项目选取，结果用于回归。

## 本地运行

安装 Python 3.12 和 Windows 版 [LTspice](https://www.analog.com/cn/resources/design-tools-and-calculators/ltspice-simulator.html)。在仓库目录用 PowerShell 执行。将示例路径改成本机路径。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$ltspice = "$env:LOCALAPPDATA\Programs\ADI\LTspice\LTspice.exe"
.\.venv\Scripts\python.exe run_evidence.py --ltspice $ltspice
```

退出码 0 表示四次回归与预期相符。反例的证据中仍会显示电路检查失败。用 `--case motor-drive --variant negative` 可单跑一份。每次在 `runs/` 下建独立目录，保存需求文本、检查声明、实际运行的 `.cir`、原始 `.raw`、LTspice 日志和 `evidence.json`。打开 `requirements` 看原需求与检查的对应关系，打开 `checks` 看数值和阈值，打开 `files` 看对应文件哈希。

## 后台 Agent 接入

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-mcp.txt
.\.venv\Scripts\python.exe smoke_mcp.py $ltspice ./mcp-smoke-runs
```

在支持 stdio MCP 的客户端添加一个本地服务。下面是采用 `mcpServers` 配置的客户端示例。把两条绝对路径换成实际安装位置。

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

- `run_circuit_example(case_id, variant)` 重跑固定的正例或反例。
- `verify_circuit_design(source_text, requirements, elements, analysis, measurements, checks)` 接收自定义电路。可以照抄 `smoke_mcp.py` 的分压器请求，再换成自己的电路和要求。
- 返回值包含测量、需求对应的检查状态、证据路径。Agent 提交的电路支持电阻、直流电流源、电压源（直流或 PWL）、线性电压控制电压源，以及瞬态电压点值、窗口极值和线性组合。元件的 `nodes` 顺序按 SPICE 定义，`0` 为参考地。当前没有原理图编辑和自定义器件模型入口。

## 怎样读结果

`linked_checks_passed_semantics_unverified` 表示关联的数值检查通过，需求解释与覆盖范围仍需审阅。没有对应检查的要求会显示为 `unresolved`。例如电机驱动的单电源实现与黑盒的器件数量在本版保留为待复核项。测量只覆盖保存的采样点和插值，原理图连接和实物表现需单独核验。小仓库直接从结构化电路生成网表，复用 spicelib 读取 RAW。MCP 复用官方 Python SDK，客户端按需启动本地子进程。

## 许可证

本仓库源码采用 GPL-3.0-only。详见 [LICENSE](LICENSE)。
