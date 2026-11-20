"""Check shared day-one contracts without starting containers (stdlib only)."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    result = subprocess.run(
        ['docker', 'compose', '--profile', '*', 'config', '--format', 'json'],
        cwd=ROOT, check=True, capture_output=True, text=True, encoding='utf-8',
    )
    config = json.loads(result.stdout)
    services = config['services']
    assert 'postgres' in services and 'broker' in services
    assert not {'dpc-postgres', 'dpc-migrate', 'kafka', 'kafka-init'} & services.keys()
    ports = []
    for name, service in services.items():
        ports.extend((str(p['published']), p.get('protocol', 'tcp')) for p in service.get('ports', []))
        for volume in service.get('volumes', []):
            if volume['type'] == 'bind':
                assert Path(volume['source']).exists(), (name, volume['source'])
        build = service.get('build')
        if build:
            context = Path(build['context'])
            assert context.is_dir(), name
            assert (context / build.get('dockerfile', 'Dockerfile')).is_file(), name
        env = service.get('environment', {})
        if 'DATABASE_URL' in env:
            assert env['DATABASE_URL'] == 'postgresql://app:app@postgres:5432/app', name
        if 'KAFKA_BOOTSTRAP' in env:
            assert env['KAFKA_BOOTSTRAP'] == 'broker:9092', name
        if 'EVENTS_TOPIC' in env:
            assert env['EVENTS_TOPIC'] == 'ticket-telemetry', name
    assert len(ports) == len(set(ports)), 'Duplicate host ports'
    for name in ('app-a', 'api', 'stream', 'broker-init'):
        env = services[name]['environment']
        assert env['TOPIC_DOMAIN_EVENTS'] == 'domain-events'
        assert env['TOPIC_NOTIFICATIONS'] == 'notifications'
        assert env['TOPIC_TICKET_TELEMETRY'] == 'ticket-telemetry'
    assert 'kafka' in services['broker']['networks']['default']['aliases']
    migrations = list((ROOT/'migrations').glob('[0-9][0-9][0-9]_*.sql'))
    numbers = [p.name[:3] for p in migrations]
    assert '001' in numbers and len(numbers) == len(set(numbers)), 'Migration numbers must be unique and retain baseline'
    assert any(v.get('target') == '/migrations' and Path(v['source']) == ROOT/'migrations'
               for v in services['migrate']['volumes'])
    schema = json.loads((ROOT/'docs/contracts/ticket-telemetry.schema.json').read_text())
    assert set(schema['required']) == {'event_id','performance_id','ticket_id','gate','sector_id','accepted','event_time'}
    print(f'PASS: {len(services)} services, {len(ports)} unique ports, shared DB/Kafka, bind paths, build contexts, topic constants and telemetry schema')


if __name__ == '__main__':
    main()
