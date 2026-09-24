import asyncio
import base64
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.lipsync_service import build_viseme_cues, word_visemes
from app.services import tts_service
from app.api.routes import voice


@pytest.mark.parametrize('text,language,expected', [
    ('મમ્મી', 'gu', 'mbp'), ('ફોન', 'gu', 'mbp'), ('હું', 'gu', 'oo'),
    ('मम्मी', 'hi', 'mbp'), ('हूँ', 'hi', 'oo'), ('मदद', 'hi', 'mbp'),
    ('mom', 'en', 'mbp'), ('five', 'en', 'fv'), ('you', 'en', 'oo'),
])
def test_multilingual_shapes(text, language, expected):
    shapes, _ = word_visemes(text, language)
    assert expected in shapes


def test_virama_does_not_insert_open_vowel_between_conjuncts():
    assert word_visemes('મ્મ', 'gu')[0] == ['mbp', 'mbp']
    assert word_visemes('म्म', 'hi')[0] == ['mbp', 'mbp']


def test_provider_gaps_and_offsets_are_preserved():
    words = [dict(text='Hello', start=.25, end=.7), dict(text='મમ્મી', start=1.2, end=1.8)]
    cues, method = build_viseme_cues(words, 'en')
    assert cues[0]['start'] == .25
    assert cues[-1]['end'] == 1.8
    assert all(c['end'] <= .7 or c['start'] >= 1.2 for c in cues)
    assert all(c['start'] < c['end'] for c in cues)
    assert all(a['end'] <= b['start'] for a,b in zip(cues,cues[1:]))
    assert 'indic-graphemes' in method


def test_punctuation_and_unsupported_script_have_no_fake_timeline():
    assert word_visemes('...', 'en')[0] == []
    assert word_visemes('你好', 'zh')[0] == []


class FakeCommunicate:
    calls = []
    def __init__(self, text, **kwargs):
        self.calls.append((text,kwargs))
    async def stream(self):
        yield {'type':'audio','data':b'ID3-test-audio'}
        yield {'type':'WordBoundary','offset':2_500_000,'duration':4_000_000,'text':'મમ્મી'}


def test_audio_and_timings_from_same_call():
    FakeCommunicate.calls.clear()
    with patch.object(tts_service.edge_tts,'Communicate',FakeCommunicate):
        result = asyncio.run(tts_service.synthesize_speech_bundle('મમ્મી','gu'))
    assert len(FakeCommunicate.calls) == 1
    assert FakeCommunicate.calls[0][1]['voice'] == 'gu-IN-DhwaniNeural'
    assert FakeCommunicate.calls[0][1]['boundary'] == 'WordBoundary'
    assert base64.b64decode(result['audio_base64']) == b'ID3-test-audio'
    assert result['words'][0]['start'] == .25
    assert result['words'][0]['end'] == .65
    assert result['visemes'][-1]['end'] == .65
    assert result['phoneme_timing'] == 'estimated-within-words'


def client():
    app=FastAPI()
    app.include_router(voice.router,prefix='/api')
    return TestClient(app)


def test_tts_failure_is_not_empty_http_200():
    async def fail(*args,**kwargs): raise RuntimeError('provider-down')
    with patch.object(voice,'synthesize_speech_bundle',fail):
        assert client().post('/api/voice/tts-sync',json={'text':'Hello'}).status_code == 502
        assert client().post('/api/voice/tts',json={'text':'Hello'}).status_code == 502


def test_api_contract_and_existing_audio_route():
    with patch.object(tts_service.edge_tts,'Communicate',FakeCommunicate):
        data=client().post('/api/voice/tts-sync',json={'text':'મમ્મી','language':'gu'})
        assert data.status_code == 200
        assert data.headers['cache-control'] == 'no-store'
        assert data.json()['visemes'][0]['viseme'] == 'mbp'
        audio=client().post('/api/voice/tts',json={'text':'મમ્મી','language':'gu'})
        assert audio.content == b'ID3-test-audio'


def test_no_unrelated_voice_for_unknown_language():
    async def empty_catalog(): return []
    with patch.object(tts_service,'_voice_catalog',empty_catalog):
        with pytest.raises(ValueError, match='No speech voice'):
            asyncio.run(tts_service.choose_voice('xx'))
