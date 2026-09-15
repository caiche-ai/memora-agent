<template>
  <section class="view chat-view project-view" id="view-project">
    <input type="file" id="project-knowledge-input" accept=".pdf,.pptx,.txt,.md,.markdown,application/pdf,application/vnd.openxmlformats-officedocument.presentationml.presentation,text/plain,text/markdown" multiple hidden>
    <div class="chat-scroll project-chat-scroll" id="project-chat-scroll">
      <div class="empty-state project-chat-empty" id="project-chat-empty">
        <div class="orb"><span>✦</span></div>
        <h2>今天想一起完成什么？</h2>
        <p>当前聊天会结合项目资料、会议和项目记忆回答。</p>
        <div class="suggestion-grid">
          <button class="suggestion project-suggestion" data-project-prompt="总结当前项目资料的核心内容"><span class="violet">▤</span><b>总结项目资料</b><small>结合资料库梳理重点</small></button>
          <button class="suggestion project-suggestion" data-project-prompt="总结当前项目的会议结论和待办"><span class="amber">◇</span><b>梳理会议</b><small>汇总会议结论与行动项</small></button>
          <button class="suggestion project-suggestion" data-project-prompt="分析当前项目的主要风险和下一步建议"><span class="blue">⌕</span><b>分析项目风险</b><small>识别风险并给出建议</small></button>
          <button class="suggestion project-suggestion" data-project-prompt="基于当前项目资料生成一份 8 页 PPT"><span class="coral">▰</span><b>制作项目 PPT</b><small>生成可下载的演示文稿</small></button>
        </div>
      </div>
      <div class="messages project-messages" id="project-messages"></div>
      <div class="project-context-response" id="project-context-response"></div>
    </div>
    <div class="composer-wrap project-composer-wrap">
      <div class="composer-project-row"><button class="composer-project-switch project-switch-button" type="button" aria-haspopup="menu" aria-expanded="false"><span class="project-switch-label">选择项目</span></button><button class="project-exit-button" type="button" title="退出项目聊天" aria-label="退出项目聊天" hidden>×</button></div>
      <div class="project-mention-strip" id="project-mention-strip" hidden></div>
      <div class="project-mention-menu" id="project-mention-menu" role="listbox" hidden></div>
      <form class="composer project-composer unified-chat-composer" id="project-chat-form">
        <label class="composer-file-plus" for="project-knowledge-input" title="上传到当前项目资料库" aria-label="上传到当前项目资料库"><span>＋</span></label>
        <input id="project-message-input" type="text" maxlength="20000" placeholder="输入 @ 引用项目文件…" autocomplete="off">
        <button type="submit" class="send-button" id="project-send-button" aria-label="发送">↑</button>
      </form>
      <p>项目聊天会使用当前项目中的资料、会议和记忆。</p>
    </div>
  </section>
</template>
