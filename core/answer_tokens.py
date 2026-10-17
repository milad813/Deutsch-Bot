"""Bind answer buttons to the question that generated them."""

from uuid import uuid4


def new_answer_token():
    return uuid4().hex[:12]


def answer_index(suffix, current):
    parts = str(suffix).split(":")
    token = current.get("answer_token")
    if token and (len(parts) != 2 or parts[0] != token):
        raise ValueError("Expired question")
    if not token and len(parts) != 1:
        raise ValueError("Expired question")
    return int(parts[-1])
