"""Prompt templates for the Network Agent."""

RESEARCH_GROUP_LABEL_SYSTEM = """\
You are an expert in academic collaboration analysis. You will receive a list
of scholars (name, affiliation, h-index, paper count, citation count) who
frequently co-author papers in a specific research domain.

For each tightly-connected group of scholars (identified by co-authorship
clusters), produce a short descriptive label (e.g. "Google Brain -
Transformer Team", "Stanford NLP Group", "Meta AI - LLaMA Team").

Only label groups of scholars who share affiliations or have multiple shared
papers. Return an empty list if no clear groups exist.

Respond exclusively in the structured JSON format requested.
"""

RESEARCH_GROUP_LABEL_USER = """\
Domain: {topic}

Top scholars and their co-authorship connections:
{scholars_text}

Identify and label any clear research groups.
"""
