import re

def clean_attendance_reason(reason_str: str | None) -> str:
    """Extract and format a clean, concise reason from user text or LLM output."""
    if not reason_str or str(reason_str).strip().lower() in ("null", "none", "not specified", "undefined"):
        return "Not specified"

    text = str(reason_str).strip()

    # Remove Discord mentions
    text = re.sub(r'<@!?\d+>', '', text)
    text = re.sub(r'@\w+', '', text)

    # Iteratively strip leading action / date / filler prefixes
    prefixes = [
        r'^(i will be|i\'ll be|i am|i\'m|im|i\'ll|ill|i will|member|user)\s+',
        r'^(taking|take|applying for|applied for|requesting|request for|request|need|need a|want a|want to take|will be|will|wont be|won\'t be|wont|won\'t)\s+(a\s+|for\s+)?(leave|lateness|late coming|coming late|running late|late|absent|coming)\s*',
        r'^(on leave|absent|coming late|running late|be late|delayed|late|leave|not coming|not come|wont come|wont be coming|won\'t come|won\'t be coming)\s*',
        r'^(today|tomorrow|yesterday|day after tomorrow)\s*',
        r'^(on\s+|for\s+|at\s+|in\s+)?\d{4}-\d{2}-\d{2}\s*',
        r'^(on\s+|for\s+|at\s+|in\s+)?\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\s*',
        r'^((for|by)\s+\d+\s*(minutes?|mins?|hours?|hrs?|days?)?\s*)',
        r'^(because of|because|coz of|coz|cause of|cause|due to|as i have|as i am|as i|as|owing to|reason:?|for my|for a|for an|for|on|at|in|of)\s+',
        r'^(i have|i am|im|i\'m|i will|i\'ll|a|an|my|the)\s+',
        r'^(will be|will|wont be|won\'t be)\s+'
    ]

    prev_text = None
    while text != prev_text:
        prev_text = text
        for p in prefixes:
            text = re.sub(p, '', text, flags=re.IGNORECASE).strip()

    suffixes = [
        r'\s+(today|tomorrow|yesterday|day after tomorrow)$',
        r'\s+(leave|lateness|late)$',
        r'\s+((by|for)\s+\d+\s*(minutes?|mins?|hours?|hrs?|days?)?)$',
    ]
    for s in suffixes:
        text = re.sub(s, '', text, flags=re.IGNORECASE).strip()

    text = text.strip(" .,:-_\"'")

    if not text or text.lower() in ("leave", "late", "because", "due", "for", "as", "to", "not specified", "coming late", "be late"):
        return "Not specified"

    return text[0].upper() + text[1:]

cases = [
    "wont be coming today due to rain",
    "taking a leave today due to exams",
    "wont come tomorrow because of fever"
]

for c in cases:
    print(f"{c!r} -> {clean_attendance_reason(c)!r}")
