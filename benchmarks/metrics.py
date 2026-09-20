import unicodedata


def normalize(text):
    """Collapse whitespace, preserving case, accents, punctuation, and reading order."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def distance(reference, prediction):
    previous = list(range(len(prediction) + 1))
    for i, expected in enumerate(reference, 1):
        current = [i]
        for j, actual in enumerate(prediction, 1):
            current.append(
                min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (expected != actual))
            )
        previous = current
    return previous[-1]


def score(reference, prediction):
    reference, prediction = normalize(reference), normalize(prediction)
    chars = distance(reference, prediction)
    words = distance(reference.split(), prediction.split())
    return {
        "character_errors": chars,
        "reference_characters": len(reference),
        "word_errors": words,
        "reference_words": len(reference.split()),
        "cer": chars / max(1, len(reference)),
        "wer": words / max(1, len(reference.split())),
    }
