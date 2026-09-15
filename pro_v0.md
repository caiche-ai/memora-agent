需求：
1、有对话页面
2、支持上传文件-pdf，作为知识背景
3、支持上传文件-txt，作为会议原文，上传完，分析会议内容，若有风险，生成待办发邮件
4、支持聊天和会议中的长记忆:人物、时间、地点、聊过的主题
5、可以联网搜索、可以制作PPT
测试点：
1、可对话
2、上传pdf背景知识
3、上传会议原文txt，分析内容若有风险生成待办，发送邮件
4、对话支持对话历史和会议的长记忆
5、问时效性信息可以联网查询
6、对话下发生成ppt明确要求，可输出 ppt；ppt可下载 或 可在线预览

关键问题：
- 长期记忆的存储、注入
1. 用户自定义哪些作为关键信息

## 用户请求数据

以下请求用于模拟“数字孪生实训平台项目”中的真实用户操作，可直接作为功能测试数据。`@文件名` 表示用户在项目聊天框中输入 `@` 后选择对应文件，不是手工拼接的普通文本。

### 一、普通对话

```json
[
  {
    "id": "chat-001",
    "scene": "基础问答",
    "request": "请介绍一下数字孪生实训平台通常包含哪些核心模块？",
    "expectedIntent": "chat",
    "expected": "返回平台模块说明，不要求调用项目资料"
  },
  {
    "id": "chat-002",
    "scene": "方案建议",
    "request": "如果后端使用 Python，请给出适合数字孪生实训平台的技术栈建议。",
    "expectedIntent": "chat",
    "expected": "给出 Python 后端、数据库、消息通信和部署建议"
  },
  {
    "id": "chat-003",
    "scene": "结构化输出",
    "request": "请把数字孪生实训平台的建设工作拆分为需求、开发、联调、测试和验收五个阶段。",
    "expectedIntent": "chat",
    "expected": "按五个阶段输出工作内容"
  }
]
```

### 二、背景知识文件问答

前置条件：向项目资料库上传以下文件中的一个或多个：

- `01_项目概述与建设方案.md`
- `02_产品需求规格说明.md`
- `03_数据与接口规范.md`
- `04_测试与验收方案.md`
- `数字孪生实训平台需求.pdf`

```json
[
  {
    "id": "rag-001",
    "scene": "单文件总结",
    "request": "@数字孪生实训平台需求.pdf 总结这份文件的主要内容。",
    "expectedIntent": "chat",
    "expectedSources": ["数字孪生实训平台需求.pdf"],
    "expected": "回答基于指定 PDF，并展示文档引用"
  },
  {
    "id": "rag-002",
    "scene": "需求提取",
    "request": "@02_产品需求规格说明.md 提取学生端和教师端的核心功能，并用表格对比。",
    "expectedIntent": "chat",
    "expectedSources": ["02_产品需求规格说明.md"],
    "expected": "区分学生端与教师端功能"
  },
  {
    "id": "rag-003",
    "scene": "多文件综合",
    "request": "@02_产品需求规格说明.md @04_测试与验收方案.md 对照需求与验收方案，找出可能遗漏的验收项。",
    "expectedIntent": "chat",
    "expectedSources": ["02_产品需求规格说明.md", "04_测试与验收方案.md"],
    "expected": "综合两个指定文件分析差异"
  },
  {
    "id": "rag-004",
    "scene": "接口查询",
    "request": "@03_数据与接口规范.md 平台需要接入哪些设备数据？接口有哪些关键约束？",
    "expectedIntent": "chat",
    "expectedSources": ["03_数据与接口规范.md"],
    "expected": "列出设备数据、协议或接口约束"
  },
  {
    "id": "rag-005",
    "scene": "风险分析",
    "request": "结合当前项目资料，分析一期建设最可能遇到的五项风险，并给出应对建议。",
    "expectedIntent": "chat",
    "expected": "自动检索当前项目资料并输出风险和建议"
  }
]
```

### 三、会议原文与会议 Artifact

前置条件：添加会议并上传：

- `2026-08-18_项目启动会.txt`
- `2026-08-21_需求评审会.txt`
- `2026-08-25_联调与风险会议.txt`

```json
[
  {
    "id": "meeting-001",
    "scene": "会议原文问答",
    "request": "@2026-08-18_项目启动会.txt 这次会议确定了哪些项目范围和里程碑？",
    "expectedIntent": "chat",
    "expected": "直接回答会议原文中的范围和里程碑，不生成 Artifact"
  },
  {
    "id": "meeting-002",
    "scene": "生成会议详情",
    "request": "@2026-08-21_需求评审会.txt 生成会议详情，突出结论、风险和待办。",
    "expectedIntent": "meeting_detail",
    "expected": "返回可编辑、可撤销、可重新生成、可保存的 Markdown 草稿"
  },
  {
    "id": "meeting-003",
    "scene": "生成会议总结",
    "request": "@2026-08-25_联调与风险会议.txt 生成一份面向项目负责人的会议总结。",
    "expectedIntent": "meeting_detail",
    "expected": "生成会议总结草稿，保存后进入该会议的 Artifacts"
  },
  {
    "id": "meeting-004",
    "scene": "生成会后邮件",
    "request": "@2026-08-25_联调与风险会议.txt 起草一封会后同步邮件，说明风险、负责人和截止时间。",
    "expectedIntent": "email_content",
    "expected": "返回可编辑邮件正文 Artifact 草稿，不自动发送"
  },
  {
    "id": "meeting-005",
    "scene": "风险提取",
    "request": "@2026-08-25_联调与风险会议.txt 会议中有哪些高风险问题？分别由谁跟进？",
    "expectedIntent": "chat",
    "expected": "基于会议原文回答风险和负责人"
  },
  {
    "id": "meeting-006",
    "scene": "跨会议对比",
    "request": "@2026-08-18_项目启动会.txt @2026-08-25_联调与风险会议.txt 对比两次会议中的项目风险变化。",
    "expectedIntent": "chat",
    "expected": "综合两个会议文件回答；不触发单会议 Artifact 生成"
  }
]
```

### 四、长期记忆

```json
[
  {
    "id": "memory-001",
    "scene": "自动提取人物和项目",
    "request": "我叫张伟，是数字孪生实训平台的项目经理，负责总体进度和验收协调。",
    "expectedIntent": "chat",
    "expectedMemory": ["person", "topic", "fact"]
  },
  {
    "id": "memory-002",
    "scene": "自动提取偏好",
    "request": "我偏好所有项目汇报先给结论，再列风险和下一步行动。",
    "expectedIntent": "chat",
    "expectedMemory": ["preference"]
  },
  {
    "id": "memory-003",
    "scene": "自动提取时间",
    "request": "数字孪生实训平台一期计划在 2026 年 9 月 30 日完成正式验收。",
    "expectedIntent": "chat",
    "expectedMemory": ["time", "fact"]
  },
  {
    "id": "memory-004",
    "scene": "记忆召回",
    "request": "我负责什么工作？这个项目什么时候验收？",
    "expectedIntent": "chat",
    "expected": "从当前作用域长期记忆中召回负责人职责和验收时间"
  },
  {
    "id": "memory-005",
    "scene": "输出偏好召回",
    "request": "按照我习惯的汇报方式，总结当前项目进展。",
    "expectedIntent": "chat",
    "expected": "优先按结论、风险、下一步行动组织回答"
  }
]
```

手动记忆测试数据：

```json
[
  {
    "type": "fact",
    "subject": "一期设备范围",
    "content": "一期只接入 CNC-01、ROBOT-02 和 LINE-03 三台设备。",
    "importance": 5,
    "pinned": true
  },
  {
    "type": "preference",
    "subject": "汇报格式",
    "content": "项目汇报先给结论，再列风险和下一步行动。",
    "importance": 4,
    "pinned": true
  },
  {
    "type": "risk",
    "subject": "ROBOT-02 数据风险",
    "content": "ROBOT-02 部分关节扭矩字段尚未开放，可能影响故障仿真。",
    "importance": 5,
    "pinned": false
  }
]
```

### 五、联网搜索

```json
[
  {
    "id": "web-001",
    "scene": "时效信息",
    "request": "查询今天数字孪生领域最值得关注的三条新闻，并附上来源。",
    "expectedIntent": "chat",
    "expectedWebSearch": true,
    "expected": "返回实时搜索结果和可访问来源"
  },
  {
    "id": "web-002",
    "scene": "最新政策",
    "request": "联网查询当前职业教育数字化实训平台相关的最新政策，概括与本项目有关的要求。",
    "expectedIntent": "chat",
    "expectedWebSearch": true,
    "expected": "搜索最新政策并结合项目场景说明"
  },
  {
    "id": "web-003",
    "scene": "最新技术资料",
    "request": "查找近期数字孪生平台在设备数据接入和三维轻量化方面的新方案。",
    "expectedIntent": "chat",
    "expectedWebSearch": true,
    "expected": "返回近期技术资料及来源"
  }
]
```

### 六、PPT 生成

```json
[
  {
    "id": "ppt-001",
    "scene": "基于项目资料生成 PPT",
    "request": "基于当前项目资料生成一份 8 页的数字孪生实训平台项目汇报 PPT，包含背景、范围、架构、进展、风险、计划和验收安排。",
    "expectedIntent": "ppt",
    "expected": "检索项目资料和项目记忆后生成可下载的 PPT Artifact"
  },
  {
    "id": "ppt-002",
    "scene": "基于指定文件生成 PPT",
    "request": "@01_项目概述与建设方案.md @04_测试与验收方案.md 生成一份面向校方领导的项目验收汇报 PPT。",
    "expectedIntent": "ppt",
    "expectedSources": ["01_项目概述与建设方案.md", "04_测试与验收方案.md"],
    "expected": "PPT Artifact 记录两个来源文件 ID"
  },
  {
    "id": "ppt-003",
    "scene": "联网增强 PPT",
    "request": "联网查询最新数字孪生实训趋势，并结合当前项目资料制作一份 10 页 PPT。",
    "expectedIntent": "ppt",
    "expectedWebSearch": true,
    "expected": "结合项目资料、记忆和联网结果生成 PPT"
  }
]
```

### 七、邮件发送

前置条件：先将会议详情、会议总结或邮件内容保存为 Artifact，并配置 AgentMail 或 SMTP。

```json
[
  {
    "id": "email-001",
    "scene": "发送会议总结",
    "operation": "点击已保存会议总结 Artifact 的邮件图标",
    "recipient": "project-owner@example.com",
    "subject": "数字孪生实训平台联调与风险会议总结",
    "expected": "打开邮件确认窗口；用户确认后发送"
  },
  {
    "id": "email-002",
    "scene": "发送待办提醒",
    "operation": "在会议待办中点击发邮件",
    "recipient": "owner@example.com",
    "subject": "待办提醒：完成 ROBOT-02 替代点位确认",
    "expected": "正文包含待办、负责人、截止时间和风险等级"
  },
  {
    "id": "email-003",
    "scene": "发送任意 Artifact",
    "operation": "点击任意已保存 Markdown Artifact 的邮件图标",
    "recipient": "team@example.com",
    "expected": "Artifact 内容自动填充为邮件正文，但发送前仍需用户确认"
  }
]
```

### 八、异常与边界请求

```json
[
  {
    "id": "edge-001",
    "request": "总结这份 PDF。",
    "precondition": "当前对话没有上传任何 PDF",
    "expected": "提示用户上传文件，不得伪造文件内容"
  },
  {
    "id": "edge-002",
    "request": "生成会议总结。",
    "precondition": "没有通过 @ 选择会议文件",
    "expected": "提示先选择会议文件"
  },
  {
    "id": "edge-003",
    "request": "@项目启动会.txt @风险会议.txt 生成会议详情。",
    "precondition": "两个文件属于不同会议",
    "expected": "提示一次只能基于一个会议生成 Artifact"
  },
  {
    "id": "edge-004",
    "request": "引用另一个项目中的文件回答问题。",
    "precondition": "请求携带不属于当前项目的 documentId",
    "expected": "后端拒绝请求，且不保存半截聊天消息"
  },
  {
    "id": "edge-005",
    "request": "上传扫描图片型 PDF 后总结内容。",
    "expected": "提示当前没有可提取文本，扫描件暂不支持 OCR"
  },
  {
    "id": "edge-006",
    "request": "发送邮件。",
    "precondition": "未填写收件人",
    "expected": "前端阻止发送并要求填写收件人"
  }
]
```
