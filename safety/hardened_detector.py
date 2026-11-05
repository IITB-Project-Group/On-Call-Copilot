"""Hardened prompt-injection detection (control IV-02).

The red team found that the baseline ``input_guardrails.InjectionDetector`` misses obfuscated and paraphrased
instructions: spaced-out letters, leetspeak, ROT13, hex, URL encoding, other languages and polite paraphrases
("kindly bounce all the pods"). ``HardenedInjectionDetector`` keeps every baseline pattern and adds

  1. normalisation passes -- de-spacing, leetspeak folding, confusable folding (Cyrillic/Greek look-alikes),
     URL, hex and ROT13 decoding -- and re-runs the baseline patterns on each normalised view;
  2. a "destructive verb + broad target" rule that catches paraphrases in English;
  3. multilingual keyword pairs (French, Spanish, German, Hindi, Portuguese) for the same intent;
  4. an operator-impersonation rule ("the SRE lead said it is fine", "approval waived").

It has the same interface as the baseline detector, so it plugs into ``InputGuardrails(detector=...)`` and
therefore into every telemetry sanitiser without modifying the copilot.
"""
from __future__ import annotations

import binascii
import codecs
import re
import unicodedata
from urllib.parse import unquote

from guardrail_core import Decision, Finding
from input_guardrails import InjectionDetector

LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i", "|": "l"})
CONFUSABLES = str.maketrans({"а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ѕ": "s",
                             "ԁ": "d", "ӏ": "l", "ο": "o", "α": "a", "ε": "e", "ι": "i", "ν": "v", "τ": "t", "κ": "k",
                             "Ѕ": "S", "Е": "E", "Т": "T", "М": "M", "А": "A", "О": "O", "Р": "P", "С": "C", "Ү": "Y"})

VERB = r"(?:restart|reboot|bounce|recycle|redeploy|kill|terminate|stop|shut\s*down|delete|drop|wipe|flush|purge|scale\s+(?:down|to\s+0)|roll\s*back|disable|turn\s+off)"
BROAD = r"(?:all|every|each|entire|whole|the\s+(?:whole|entire))\s+(?:the\s+)?(?:\w+\s+){0,2}(?:services?|pods?|containers?|nodes?|cluster|fleet|deployments?|instances?|apps?|systems?|everything)"
PARAPHRASE = re.compile(rf"\b{VERB}\b[^.\n]{{0,40}}\b{BROAD}\b|\b{VERB}\s+everything\b", re.I)
IMPERSONATION = re.compile(r"\b(?:sre|on-?call|incident)\s+(?:lead|commander|manager)\s+(?:said|says|approved|confirmed)\b|"
                           r"\b(?:approval|review)\s+(?:is\s+)?(?:waived|not\s+(?:needed|required))\b|\bpre-?approved\b", re.I)
MULTILINGUAL = [  # (language, destructive verb, broad target)
    ("fr", r"red[ée]marr|arr[êe]t|supprim|red[ée]ploy", r"tous\s+les|toutes\s+les|chaque"),
    ("es", r"reinici|deten|elimin|apag", r"todos\s+los|todas\s+las|cada"),
    ("de", r"neu\s*starten|neustart|stopp|l[öo]sch|beend", r"alle|jeden|s[äa]mtliche"),
    ("pt", r"reinici|par[ae]|exclu|deslig", r"todos\s+os|todas\s+as|cada"),
    ("hi", r"पुनः\s*आरंभ|रीस्टार्ट|बंद|हटा", r"हर|सभी|सारी|सारे"),
]
# letters spaced out with NO word gaps ("r e s t a r t e v e r y s e r v i c e") lose their word boundaries;
# match the run-together form, but only when the text really is letter-by-letter spaced (keeps normal lines quiet)
COMPACT = re.compile(r"(?:restart|reboot|bounce|recycle|redeploy|kill|terminate|stop|shutdown|delete|wipe|purge)(?:the)?"
                     r"(?:all|every|each|entire|whole)(?:the)?(?:services?|pods?|containers?|nodes?|cluster|deployments?|instances?|everything)"
                     r"|ignore(?:all|any)?(?:previous|prior|above)instructions|system:?(?:restart|ignore|approval)")
SPACED_RUN = re.compile(r"(?:\b\w\b\s+){5,}\b\w\b")
ROLE_WORDS = re.compile(r"\b(?:system|systeme|système|sistema|सिस्टम)\s*[:：]", re.I)


def _despace(t: str) -> str:
    # "r e s t a r t   e v e r y" -> "restart every"  (single letters separated by single spaces)
    return re.sub(r"(?<!\w)((?:\w ){2,}\w)(?!\w)", lambda m: m.group(1).replace(" ", ""), t)


def _hex(t: str) -> str:
    out = []
    for m in re.finditer(r"\b(?:[0-9a-fA-F]{2}){8,}\b", t):
        try:
            out.append(binascii.unhexlify(m.group(0)).decode("utf-8", "ignore"))
        except (binascii.Error, ValueError):
            pass
    return " ".join(out)


def normalised_views(text: str) -> dict[str, str]:
    base = unicodedata.normalize("NFKC", text)
    views = {
        "confusables": base.translate(CONFUSABLES),
        "despaced": _despace(base),
        "leetspeak": base.lower().translate(LEET),
        "url_decoded": unquote(unquote(base)),
        "hex_decoded": _hex(base),
        "rot13": codecs.decode(base, "rot_13"),
    }
    return {k: v for k, v in views.items() if v and v != text}


class HardenedInjectionDetector(InjectionDetector):
    def scan(self, text: str, location: str = "", guardrail: str = "prompt_injection",
             action: Decision = Decision.QUARANTINE) -> list[Finding]:
        findings = super().scan(text, location, guardrail, action)
        seen = {f.code for f in findings}

        def add(code: str, msg: str, sev: str = "high") -> None:
            if code not in seen:
                seen.add(code)
                findings.append(Finding(guardrail, code, msg, action, sev, location))

        for name, view in normalised_views(text).items():
            if super().scan(view, location, guardrail, action) or PARAPHRASE.search(view):
                add(f"obfuscated_injection_{name}", f"Instruction-like content after {name} normalisation")
        if SPACED_RUN.search(text):
            compact = re.sub(r"[^a-z:]", "", unicodedata.normalize("NFKC", text).lower().translate(LEET))
            if COMPACT.search(compact):
                add("obfuscated_injection_spaced_compact", "Instruction spelled out letter by letter")
        if PARAPHRASE.search(text):
            add("paraphrased_destructive_command", "Destructive verb aimed at a broad target")
        if IMPERSONATION.search(text):
            add("operator_impersonation", "Claims authority or waives approval", "medium")
        low = text.lower()
        for lang, verb, broad in MULTILINGUAL:
            if re.search(verb, low) and re.search(broad, low):
                add(f"multilingual_injection_{lang}", f"Destructive instruction in language '{lang}'")
        if ROLE_WORDS.search(text):
            add("role_marker_multilingual", "Role marker (system:) in untrusted data", "medium")
        return findings


def hardened_input_guardrails(**kw):
    """InputGuardrails with the hardened detector (drop-in for the copilot)."""
    from input_guardrails import InputGuardrails

    kw.setdefault("detector", HardenedInjectionDetector())
    return InputGuardrails(**kw)
