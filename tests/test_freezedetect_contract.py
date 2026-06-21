"""Pure-unit contract guard for the freezedetect noise threshold constant.

RC-8 follow-up: the production default noise threshold Composer ships is
asserted to lie in ffmpeg freezedetect's legal [0, 1] range on EVERY offline
gate run, regardless of whether ffmpeg is installed (the heavier
``test_real_ffmpeg_accepts_default_freezedetect_noise_threshold`` is now marked
``@pytest.mark.integration`` and skips in the offline gate). This guards the
contract that the historical negative-dB value violated.
"""

from clipper_agency.agents.composer import _FREEZE_NOISE_THRESHOLD


def test_freeze_noise_threshold_is_in_legal_unit_range():
    """freezedetect's ``n`` parameter is a noise-tolerance ratio in [0, 1].

    A value outside this range (e.g. a historical dB value like -30.0) is
    rejected by ffmpeg with ``out of range [0 - 1]`` and silently breaks freeze
    detection. The production default must satisfy ffmpeg's contract.
    """
    assert 0.0 <= _FREEZE_NOISE_THRESHOLD <= 1.0
