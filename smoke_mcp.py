"""Test actual MCP tool calls with a stdio client and live LTspice."""
import asyncio
import json
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from run_evidence import ROOT


async def main(exe, output):
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / 'mcp_server.py')],
        env={'CIRCUIT_EVIDENCE_LTSPICE': exe, 'CIRCUIT_EVIDENCE_OUTPUT': output})
    results = []
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = {tool.name for tool in (await session.list_tools()).tools}
            assert tools == {'run_circuit_example', 'verify_circuit_design'}, tools
            for case_id, variant, fails in [('motor-drive', 'positive', 0), ('motor-drive', 'negative', 8),
                                           ('resistor-blackbox', 'positive', 0), ('resistor-blackbox', 'negative', 2)]:
                reply = await session.call_tool('run_circuit_example', {'case_id': case_id, 'variant': variant})
                assert not reply.isError, reply
                row = reply.structuredContent
                assert row['regression_passed'] and row['summary']['failed'] == fails, row
                assert Path(row['evidence_file']).is_file()
                results.append({'case': case_id, 'variant': variant, **row['summary'], 'file': row['evidence_file']})
            # Submit an agent-supplied design with a new divider and new requirement/check.
            check = {'id': 'divider-output', 'origin': 'original', 'description': 'Half-voltage check',
                     'kind': 'measurement', 'comparison': '>=', 'threshold': 1.999,
                     'uncertainty': None, 'index': 0, 'scale': 1}
            args = {
                'source_text': 'Measure at least 1.999 V at the divider output.',
                'requirements': [{'id': 'output', 'quote': 'Measure at least 1.999 V at the divider output.',
                                  'status': 'bound', 'bindings': [{'path': ['checks', 0], 'expected': check}]}],
                'elements': [{'kind': 'V', 'ref': 'VIN', 'nodes': ['in', '0'], 'source': {'dc_v': 4}},
                             {'kind': 'R', 'ref': 'R1', 'nodes': ['in', 'out'], 'value': 1000},
                             {'kind': 'R', 'ref': 'R2', 'nodes': ['out', '0'], 'value': 1000}],
                'analysis': {'stop_s': .001, 'max_step_s': .00001},
                'measurements': [{'kind': 'voltage', 'positive': 'out', 'negative': '0', 'at_s': .0005}],
                'checks': [check],
            }
            reply = await session.call_tool('verify_circuit_design', args)
            assert not reply.isError, reply
            row = reply.structuredContent
            assert abs(row['measurements'][0]['value'] - 2) < 1e-6 and row['summary']['passed'] == 1, row
            results.append({'case': 'custom-divider', 'voltage_v': row['measurements'][0]['value'],
                            'file': row['evidence_file']})
            args['requirements'][0]['quote'] = 'Different text.'
            rejected = await session.call_tool('verify_circuit_design', args)
            assert rejected.isError and 'occur verbatim' in str(rejected.content), rejected
            results.append({'case': 'custom-divider-altered-quote', 'rejected': True})
            args['requirements'][0]['quote'] = args['source_text']
            args['requirements'][0]['bindings'][0]['expected'] = {**check, 'scale': True}
            rejected = await session.call_tool('verify_circuit_design', args)
            assert rejected.isError and 'differs in value or type' in str(rejected.content), rejected
            results.append({'case': 'custom-divider-altered-check-type', 'rejected': True})
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1], sys.argv[2]))
