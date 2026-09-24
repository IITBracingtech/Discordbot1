def classify(user_text):
    text_lower = user_text.lower()
    late_keywords = ["late", "delayed", "delay", "coming late", "running late", "reach late", "be late"]
    if any(kw in text_lower for kw in late_keywords):
        return "late"
    return "leave"

cases = [
    "request for late coming because of traffic",
    "coming late by 30 mins",
    "delayed due to rain"
]

for c in cases:
    print(f"{c} -> {classify(c)}")
