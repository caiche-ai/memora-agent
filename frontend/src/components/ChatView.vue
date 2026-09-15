<template>
  <section class="view chat-view active" id="view-chat">
    <div class="chat-scroll" id="chat-scroll">
      <div class="empty-state" id="chat-empty">
        <div class="orb"><span>✦</span></div>
        <h2>今天想一起完成什么？</h2>
        <p>我能理解文档、分析会议、记住重要信息，也能搜索最新资料和制作演示文稿。</p>
        <div class="suggestion-grid">
          <button class="suggestion" data-prompt="总结我上传的文件中最重要的内容"><span class="violet">▤</span><b>阅读文档</b><small>上传文件，基于原文回答</small></button>
          <button class="suggestion" data-view-target="project"><span class="amber">◇</span><b>分析会议</b><small>进入项目管理会议与待办</small></button>
          <button class="suggestion" data-prompt="帮我联网查询今天最值得关注的科技新闻"><span class="blue">⌁</span><b>联网搜索</b><small>查询实时信息并附来源</small></button>
          <button class="suggestion" data-prompt="帮我制作一份关于人工智能行业趋势的 8 页 PPT"><span class="coral">▰</span><b>制作 PPT</b><small>生成可下载的演示文稿</small></button>
        </div>
      </div>
      <div class="messages" id="messages"></div>
    </div>

    <div class="composer-wrap">
      <div class="document-strip" id="document-strip"></div>
      <div class="composer-project-row"><button class="composer-project-switch project-switch-button" type="button" aria-haspopup="menu" aria-expanded="false"><span class="project-switch-label">选择项目</span></button><button class="project-exit-button" type="button" title="退出项目聊天" aria-label="退出项目聊天" hidden>×</button></div>
      <form class="composer unified-chat-composer" id="chat-form">
        <label class="composer-file-plus" title="上传文件" aria-label="上传文件">
          <input type="file" id="knowledge-input" accept=".pdf,.pptx,.txt,.md,.markdown,application/pdf,application/vnd.openxmlformats-officedocument.presentationml.presentation,text/plain,text/markdown" multiple hidden>
          <span>＋</span>
        </label>
        <input id="message-input" type="text" maxlength="20000" placeholder="输入消息，或明确要求生成一份 PPT…" autocomplete="off">
        <button type="submit" class="send-button" id="send-button" aria-label="发送">↑</button>
      </form>
      <p class="disclaimer">AI 可能会犯错，重要信息请核实。邮件仅在你确认后发送。</p>
    </div>
  </section>
</template>
