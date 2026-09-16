import asyncio
from unittest.mock import AsyncMock, patch
import pytest
from app.voice import speak_into_meeting


def test_failed_synthesis_never_plays_robotic_fallback():
    page = AsyncMock()
    with patch('app.voice.synthesize_voice', new=AsyncMock(side_effect=RuntimeError('unavailable'))):
        with pytest.raises(RuntimeError, match='unavailable'):
            asyncio.run(speak_into_meeting(page, 'Welcome'))
    page.evaluate.assert_not_awaited()


def test_neural_audio_is_sent_to_meeting_microphone():
    page = AsyncMock()
    page.evaluate.return_value = True
    with patch('app.voice.synthesize_voice', new=AsyncMock(return_value=b'natural audio')):
        assert asyncio.run(speak_into_meeting(page, 'Welcome'))
    assert page.evaluate.await_args.args[1] == 'bmF0dXJhbCBhdWRpbw=='

