from __future__ import annotations

import os

# 自动化测试不调用外部模型或搜索服务，也不会消耗真实 API 额度。
os.environ["LLM_API_KEY"] = ""
os.environ["TAVILY_API_KEY"] = ""
os.environ["SMTP_HOST"] = ""
os.environ["AGENTMAIL_API_KEY"] = ""
os.environ["AGENTMAIL_INBOX_ID"] = ""
