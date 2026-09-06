import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.agent.tools import workflow_tools as tools


def test_catalog_index_fits_model_context_and_details_are_available():
    index = asyncio.run(tools._list_node_types_handler({}, None))
    assert len(json.dumps(index, ensure_ascii=False)) < 12000
    assert any(node['type'] == 'llm' for node in index['node_types'])
    detail = asyncio.run(tools._list_node_types_handler({'types': ['llm']}, None))
    assert [node['type'] for node in detail['node_types']] == ['llm']
    assert any(field['name'] == 'prompt' for field in detail['node_types'][0]['config_fields'])


def test_invalid_draft_is_previewed_with_errors():
    failure = {'ok': False, 'issues': [{'level': 'error', 'message': 'missing trigger'}]}
    with patch.object(tools, '_validate_workflow_handler', AsyncMock(return_value=failure)):
        result = asyncio.run(tools._propose_workflow_handler({'name': 'Draft', 'definition': {'nodes': []}}, None))
    assert result['ok'] is False
    assert result['definition'] == {'nodes': []}
    assert result['issues'] == failure['issues']


def test_save_resolves_last_draft_before_confirmation():
    draft = {'name': 'Report', 'definition': {'nodes': [{'id': 'start'}], 'edges': []}}
    with patch.object(tools, '_latest_proposed_definition', return_value=draft), patch.object(
        tools, '_validate_workflow_handler', AsyncMock(return_value={'ok': True})
    ):
        result = asyncio.run(tools.prepare_workflow_save({}, None))
    assert result['arguments'] == draft


def test_invalid_schedule_is_blocked_before_write():
    with patch.object(tools, '_validate_workflow_handler', AsyncMock(return_value={'ok': True})):
        for args in ({'schedule_enabled': True}, {'schedule_cron': 'bad cron'}):
            result = asyncio.run(tools._save_workflow_handler(
                {'name': 'Report', 'definition': {'nodes': [{}]}, **args}, SimpleNamespace()
            ))
            assert result['ok'] is False


def test_builder_rejects_tools_outside_its_catalog():
    from app.agent.loop import AgentLoop
    loop = object.__new__(AgentLoop)
    loop.db = None
    loop.conversation_id = 'test'

    async def run():
        return [event async for event in loop._builder_execute_call('call', 'delete_file', {}, 1, 'test')]

    with patch('app.agent.loop.crud_msg.add'), patch.object(tools.tool_registry, 'execute', AsyncMock()) as execute:
        events = asyncio.run(run())
    execute.assert_not_called()
    assert 'not available' in loop._last_builder_result['error']
    assert len(events) == 2


def test_valid_workflow_is_saved_and_its_step_executes():
    from app.services.workflow_engine import _exec_transform

    class Session:
        saved = None

        def add(self, workflow):
            self.saved = workflow

        def commit(self):
            self.saved.id = uuid4()

        def refresh(self, workflow):
            pass

    owner = SimpleNamespace(id=uuid4(), role='user', is_superuser=False)
    db = Session()
    definition = {'nodes': [
        {'id': 'start', 'type': 'trigger_manual', 'data': {'config': {}}},
        {'id': 'result', 'type': 'transform', 'data': {'config': {
            'mappings': [{'target': 'message', 'value': 'Ready'}]
        }}},
    ], 'edges': [{'id': 'edge', 'source': 'start', 'target': 'result'}]}
    with patch.object(tools, '_owner', return_value=owner):
        result = asyncio.run(tools._save_workflow_handler(
            {'name': 'Generated workflow', 'definition': definition}, SimpleNamespace(db=db)
        ))
    assert result['ok'] is True
    assert result['workflow_id'] == str(db.saved.id)
    assert db.saved.user_id == owner.id
    assert _exec_transform(db, db.saved.definition['nodes'][1]['data']['config'], {}, lambda _: None) == {'message': 'Ready'}


def test_cloud_credentials_use_connection_flow_without_secrets():
    for kind in ('gdrive', 'onedrive'):
        result = asyncio.run(tools._request_credential_handler({'kind': kind}, None))
        assert result['status'] == 'awaiting_connection'
        assert 'fields' not in result
