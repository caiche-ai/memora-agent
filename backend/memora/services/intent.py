from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .ppt import is_ppt_request
from .search import needs_web_search

IntentName = Literal["chat", "ppt", "meeting_detail", "email_content"]

MEETING_DETAIL_PATTERN = re.compile(
    r"(?:生成|写|整理|总结).*(?:会议详情|会议纪要|会议总结)|会议(?:详情|纪要|总结)", re.I
)
EMAIL_CONTENT_PATTERN = re.compile(r"(?:生成|写|整理|起草).*(?:邮件|mail)|邮件(?:内容|草稿)", re.I)


@dataclass(frozen=True)
class IntentDecision:
    name: IntentName
    web_search: bool
    reason: str


def route_intent(query: str) -> IntentDecision:
    if is_ppt_request(query):
        return IntentDecision("ppt", needs_web_search(query), "matched_ppt_rule")
    if EMAIL_CONTENT_PATTERN.search(query):
        return IntentDecision("email_content", needs_web_search(query), "matched_email_content_rule")
    if MEETING_DETAIL_PATTERN.search(query):
        return IntentDecision("meeting_detail", needs_web_search(query), "matched_meeting_detail_rule")
    return IntentDecision("chat", needs_web_search(query), "default_chat")
