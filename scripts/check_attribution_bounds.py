#!/usr/bin/env python3
"""Check adversarial attribution through an already-running selected mode."""
import argparse
import json
import os

import toolkit


def check(mode: str) -> None:
    toolkit.load_env_file()
    payload = json.loads(toolkit.render_fixture(toolkit.ROOT / 'examples/otlp/claude-code-token-metrics.json'))
    resource = payload['resourceMetrics'][0]
    # Separate from existing smoke totals while retaining dashboard fixture exclusion.
    resource['resource']['attributes'][0]['value']['stringValue'] = 'claude-code-desktop'
    metric = resource['scopeMetrics'][0]['metrics'][0]
    points = metric['sum']['dataPoints']
    for index, point in enumerate(points):
        for attr in point['attributes']:
            if attr['key'] in {'skill.name', 'mcp_server.name', 'mcp_tool.name'}:
                attr['value']['stringValue'] = f'ATTRIBUTION_PRIVATE_SENTINEL_{index}@example.invalid/path/{index}'
    status, body = toolkit.http('POST', f"http://127.0.0.1:{os.getenv('OTLP_HTTP_PORT', '4318')}/v1/metrics",
                               data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    if status != 200 or json.loads(body or b'{}').get('partialSuccess'):
        raise RuntimeError('Attribution fixture was not fully accepted')
    selector = '{service_name="claude-code-desktop",service_namespace="ai-collaboration-fixture"}'
    for name in ('claude_code_token_usage', 'ai_agent_request_token_usage_total'):
        rows = toolkit.retry(name, lambda: toolkit.prometheus_query(name + selector), lambda rows: len(rows) == 4)
        if abs(sum(float(row['value'][1]) for row in rows) - 4720) > 0.001:
            raise RuntimeError(f'{name}: token totals changed')
        for row in rows:
            labels = row['metric']
            if 'ATTRIBUTION_PRIVATE_SENTINEL' in json.dumps(labels):
                raise RuntimeError('Unbounded attribution leaked')
            if mode == 'corporate':
                if any(k in labels for k in ('skill_id', 'skill_name', 'mcp_server_name', 'mcp_tool_name')):
                    raise RuntimeError('Corporate attribution was not removed')
            elif name.startswith('ai_agent'):
                if (labels.get('skill_id'), labels.get('mcp_server_name'), labels.get('mcp_tool_name')) != ('other', 'custom', 'custom'):
                    raise RuntimeError('Canonical attribution was not bounded')
    print(f'PASS: {mode} arbitrary attribution values bounded; raw/canonical totals preserved')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=sorted(toolkit.MODES), required=True)
    check(parser.parse_args().mode)
