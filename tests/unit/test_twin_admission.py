"""Independent current validation must be fresh and bound to exact services."""

from dataclasses import replace
from datetime import timedelta

import pytest

from contractcapsule.swap.trees import RunnerError
from contractcapsule.swap.twin_models import TwinFailure
from contractcapsule.validate.approvals import ApprovalError
from contractcapsule.validate.integrity import ValidationService
from contractcapsule.validate.journal import RecordError
from tests.m5_twin_helpers import TwinFixture


def test_cached_true_report_cannot_replace_another_stages_validation(tmp_path, monkeypatch):
    fixture = TwinFixture(tmp_path)
    bound, binding = fixture.runner._bind(fixture.approval)
    views = tuple(s.compiler.compile_view(s.request) for s in fixture.runner.services)
    admissions = []
    fixture.runner._fresh(bound, binding, fixture.approval, views, admissions)
    cached = admissions[0].reports[2]
    real = ValidationService.validate_compression
    monkeypatch.setattr(ValidationService, 'validate_compression', lambda s, *args: cached if s is fixture.old_validation else real(s, *args))
    altered = views[0].model_copy(update={"content": views[0].content + "tamper"})
    with pytest.raises(RecordError):
        fixture.runner._fresh(bound, binding, fixture.approval, (altered, views[1]), admissions)


def test_same_service_class_version_with_different_configuration_changes_binding(tmp_path, monkeypatch):
    fixture = TwinFixture(tmp_path)
    _, before = fixture.runner._bind(fixture.approval)
    counter_type = type(fixture.old_validation.compiler.counter)
    monkeypatch.setattr(counter_type, 'config_digest', property(lambda _: 'sha256:' + 'd' * 64))
    _, after = fixture.runner._bind(fixture.approval)
    assert before != after


@pytest.mark.parametrize('field', ['task', 'budget', 'model_id', 'capsules', 'runtime_config'])
def test_explicit_compile_requests_cannot_disagree_with_the_replacement(tmp_path, field):
    fixture = TwinFixture(tmp_path)
    request = fixture.old_validation.request
    value = {'task': request.task.model_copy(update={'text': 'different'}),
             'budget': request.budget.model_copy(update={'model_input_tokens': 2}),
             'model_id': 'foreign', 'capsules': (fixture.new,),
             'runtime_config': {'expanded_handles': ()}}[field]
    service = replace(fixture.old_validation, request=request.model_copy(update={field: value}))
    runner = replace(fixture.runner, old_validation=service)
    assert isinstance(runner.run(fixture.approval), TwinFailure)


def test_scope_distinguishes_same_operation_in_different_environments(tmp_path):
    fixture = TwinFixture(tmp_path)
    old_key = fixture.runner._attempt_key(fixture.bound)
    new_request = fixture.request.model_copy(update={'task': fixture.request.task.model_copy(update={'environment': 'dev'})})
    other = fixture.bound.model_copy(update={'request': new_request})
    assert old_key != fixture.runner._attempt_key(other)
    fixture.attempts.reserve(old_key, 'original')
    assert fixture.attempts.reserve(fixture.runner._attempt_key(other), 'second-scope').state == 'RUNNING'


def test_source_mapping_does_not_collapse_case_sensitive_repository_names(tmp_path):
    fixture = TwinFixture(tmp_path)
    runner = replace(fixture.runner, repositories={'example/API': fixture.source})
    assert isinstance(runner.run(fixture.approval), TwinFailure)


def test_current_stage_revalidates_after_clock_advance(tmp_path):
    fixture = TwinFixture(tmp_path)
    bound, binding = fixture.runner._bind(fixture.approval)
    views = tuple(s.compiler.compile_view(s.request) for s in fixture.runner.services)
    fixture.now += timedelta(days=1000)
    with pytest.raises((RunnerError, ApprovalError)):
        fixture.runner._fresh(bound, binding, fixture.approval, views, [])
