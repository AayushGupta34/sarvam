"""22 scheduled languages plus Indian English, with Sarvam routing per language.

Mirror of frontend/src/config/languages.ts. Model support follows docs.sarvam.ai:
Mayura covers 11 codes, Sarvam-Translate and Saaras all 23, bulbul:v4-flash 9 of
the 11 TTS codes (no Malayalam or Odia), bulbul:v3 all 11.
"""
from __future__ import annotations

from dataclasses import dataclass

TRANSLATE_PRIMARY = "sarvam-translate:v1"
TRANSLATE_MAYURA = "mayura:v1"
STT_MODEL = "saaras:v4"
TTS_FLASH = "bulbul:v4-flash"
TTS_STABLE = "bulbul:v3"
STT_MODES = ("transcribe", "translate", "verbatim", "translit", "codemix")
MAX_KEYTERMS = 50
MAX_KEYTERM_CHARS = 64


@dataclass(frozen=True)
class Language:
    name: str
    code: str
    native: str
    mayura: bool = False
    tts_model: str | None = None
    # bulbul language used to read this script aloud when there is no native voice
    tts_bridge: str | None = None

    @property
    def translate_models(self) -> tuple[str, ...]:
        if self.code == "en-IN":
            return ()
        return (TRANSLATE_PRIMARY, TRANSLATE_MAYURA) if self.mayura else (TRANSLATE_PRIMARY,)


LANGUAGES: tuple[Language, ...] = (
    Language("Assamese", "as-IN", "অসমীয়া", tts_bridge="bn-IN"),
    Language("Bengali", "bn-IN", "বাংলা", True, TTS_FLASH),
    Language("Bodo", "brx-IN", "बड़ो", tts_bridge="hi-IN"),
    Language("Dogri", "doi-IN", "डोगरी", tts_bridge="hi-IN"),
    Language("Gujarati", "gu-IN", "ગુજરાતી", True, TTS_FLASH),
    Language("Hindi", "hi-IN", "हिन्दी", True, TTS_FLASH),
    Language("Kannada", "kn-IN", "ಕನ್ನಡ", True, TTS_FLASH),
    Language("Kashmiri", "ks-IN", "कॉशुर / کٲشُر", tts_bridge="hi-IN"),
    Language("Konkani", "kok-IN", "कोंकणी", tts_bridge="hi-IN"),
    Language("Maithili", "mai-IN", "मैथिली", tts_bridge="hi-IN"),
    Language("Malayalam", "ml-IN", "മലയാളം", True, TTS_STABLE),
    Language("Manipuri", "mni-IN", "মৈতৈলোন্", tts_bridge="bn-IN"),
    Language("Marathi", "mr-IN", "मराठी", True, TTS_FLASH),
    Language("Nepali", "ne-IN", "नेपाली", tts_bridge="hi-IN"),
    Language("Odia", "od-IN", "ଓଡ଼ିଆ", True, TTS_STABLE),
    Language("Punjabi", "pa-IN", "ਪੰਜਾਬੀ", True, TTS_FLASH),
    Language("Sanskrit", "sa-IN", "संस्कृतम्", tts_bridge="hi-IN"),
    Language("Santali", "sat-IN", "ᱥᱟᱱᱛᱟᱲᱤ", tts_bridge="hi-IN"),
    Language("Sindhi", "sd-IN", "सिन्धी / سنڌي", tts_bridge="hi-IN"),
    Language("Tamil", "ta-IN", "தமிழ்", True, TTS_FLASH),
    Language("Telugu", "te-IN", "తెలుగు", True, TTS_FLASH),
    Language("Urdu", "ur-IN", "اردو", tts_bridge="hi-IN"),
    Language("English (India)", "en-IN", "English", True, TTS_FLASH),
)
BY_CODE: dict[str, Language] = {lang.code: lang for lang in LANGUAGES}


def get_language(code: str) -> Language:
    try:
        return BY_CODE[code]
    except KeyError:
        raise ValueError(f"unsupported language code: {code}") from None


def route_translation(code: str, prefer_code_mixed: bool = False) -> tuple[str, str] | None:
    """Return (model, mode), or None when no translation is needed."""
    lang = get_language(code)
    if code == "en-IN":
        return None
    if prefer_code_mixed and lang.mayura:
        return TRANSLATE_MAYURA, "code-mixed"
    return TRANSLATE_PRIMARY, "formal"
