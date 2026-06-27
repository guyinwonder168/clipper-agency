# AV-Drift Diagnosis — job_8

- provider: `gemini_tts`
- video_duration_sec: 30.550
- voiceover_duration_sec: 34.091
- transition_count: 7

| beat_id | section | beat_word_start | beat_word_end | scene_planned_start | scene_planned_end | scene_achieved_start | scene_achieved_end | caption_window_start | caption_window_end | offset_ms_planned | offset_ms_achieved | offset_ms_predicted_margin |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | hook | 0.000 | 6.734 | 0.000 | 6.734 | 0.000 | 7.600 | 0.000 | 6.734 | 0.000 | 0.000 | 0.000 |
| 2 | story_1 | 6.734 | 10.943 | 6.734 | 10.943 | 7.600 | 11.467 | 6.734 | 10.943 | 0.000 | 866.000 | 100.000 |
| 3 | story_1_reveal | 10.943 | 13.047 | 10.943 | 13.047 | 11.467 | 12.633 | 10.943 | 13.047 | 0.000 | 523.700 | 200.000 |
| 4 | story_2 | 13.047 | 15.993 | 13.047 | 15.993 | 12.633 | 15.100 | 13.047 | 15.993 | 0.000 | -413.700 | 300.000 |
| 5 | story_2_reveal | 15.993 | 17.677 | 15.993 | 17.677 | 15.100 | 17.133 | 15.993 | 17.677 | 0.000 | -893.000 | 400.000 |
| 6 | story_3 | 17.677 | 20.202 | 17.677 | 20.202 | 17.133 | 17.900 | 17.677 | 20.202 | 0.000 | -543.700 | 500.000 |
| 7 | reaction | 20.202 | 21.465 | 20.202 | 21.465 | 17.900 | - | 20.202 | 21.465 | 0.000 | -2302.000 | 600.000 |
| 8 | closing_cta | 21.465 | 23.569 | 21.465 | 34.091 | - | - | 21.465 | 23.569 | 0.000 | - | 700.000 |

**transition_count**: 7

## Notes

- provider is gemini_tts; measured fallback-TTS path (no ElevenLabs job available)
- rendered_scene_manifest not persisted; PLANNED via canonical timeline (build_canonical_timeline, ADR 0020)
