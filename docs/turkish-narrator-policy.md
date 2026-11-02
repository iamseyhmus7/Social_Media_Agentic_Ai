# Turkish narrator policy

`language_code: "tr"` is the ElevenLabs ISO 639-1 request value. The string
`Turkish` is not used in that API field.

New runs snapshot `elevenlabs_turkish_only=true` and the existing free-voice policy.
Account candidates must have a Turkish language label (`tr` or its named metadata
aliases); having a Turkish entry in `verified_languages` alone does not establish
that the narrator is Turkish. The existing free API policy continues to exclude
community/library and custom-rate voices. Native filtering has no foreign-voice
fallback. Voice names are never used as language evidence.

The existing casting pipeline generates the same Turkish sample with candidate
voices. Only completed TTS samples count as API-access verified; permission, quota
and authentication failures remain distinct. A selected plan records native-language
metadata and API-access verification. `free_users_allowed` on a library voice is
not proof of free API entitlement.

Existing snapshots default to the previous policy and completed speech is preserved.
The current account was checked read-only: its 21 built-in candidates all had English
language labels; no native-Turkish candidate passed this strict free/account policy.
New selections therefore report an explicit availability error until eligible Turkish
voices are available; no generation quota was spent on this catalog check.

Official references:
- https://elevenlabs.io/docs/api-reference/text-to-dialogue/convert/
- https://elevenlabs.io/docs/eleven-creative/voices/voice-library
