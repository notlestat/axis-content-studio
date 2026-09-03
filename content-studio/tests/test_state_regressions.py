import json

import pytest
import yaml
from studio.analysis import import_analysis, transcript
from studio.cli import approve
from studio.graphics import brand_logo
from studio.models import Cut
from studio.storage import StudioError
from studio.transcription import transcribe


def test_audio_track_change_invalidates_transcript(project):
    config = project.studio.root / 'config/studio.yaml'
    config.parent.mkdir(exist_ok=True)
    config.write_text('audio_track: 1\n')
    with pytest.raises(StudioError, match='different audio track'):
        transcript(project)


def test_provider_change_does_not_reuse_old_transcript(project, monkeypatch):
    def stop_before_extract(*args):
        raise RuntimeError('new provider requested')
    class Adapter:
        extract_audio = staticmethod(stop_before_extract)
    monkeypatch.setattr('studio.transcription.helper', lambda _: Adapter())
    with pytest.raises(RuntimeError, match='new provider requested'):
        transcribe(project, provider='local')


def test_qc_rejects_stale_render_even_after_plan_review(project, proposal, tmp_path):
    path = tmp_path / 'proposal.json'
    path.write_text(json.dumps(proposal))
    import_analysis(project, path)
    project.write('logs/render-manifest.json', {'c01': {'production_digest': 'old-plan'}})
    for stage in ['transcript', 'plan', 'graphics']:
        project.approve(stage, 'Reviewed')
    with pytest.raises(StudioError, match='changed after rendering'):
        approve(project, 'qc', 'Checked outputs')


def test_brand_logo_requires_existing_client_brand_asset(project):
    profile = project.profile.model_dump()
    profile['brand']['logo'] = 'brand/logos/missing.png'
    (project.studio.client_path(project.client_slug) / 'client.yaml').write_text(yaml.safe_dump(profile))
    with pytest.raises(StudioError, match='logo is missing'):
        brand_logo(project)


def test_crop_switch_uses_source_time_without_audio_cut():
    from studio.framing import filter_for
    cut = Cut(source='source', start=100, end=125, reason='Continuous speech', crop_x=.8,
              crop_keyframes=[{'timestamp': 112.3, 'x': .4}])
    result = filter_for((1080, 1920), .8, 1, '#141820', cut.crop_keyframes, cut.start)
    assert '12.3' in result
    assert '0.4' in result
