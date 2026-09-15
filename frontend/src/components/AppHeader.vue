<template>
  <header class="topbar">
    <button class="icon-btn menu-btn mobile-only" id="open-sidebar" aria-label="打开导航">☰</button>
    <button class="icon-btn sidebar-toggle desktop-only" id="toggle-sidebar" type="button" title="收起侧边栏" aria-label="收起侧边栏">☰</button>
    <div class="topbar-copy">
      <div class="topbar-title-line"><h1 id="page-title">新对话</h1></div>
      <p id="page-subtitle">知识、记忆和工具，都在同一个对话里</p>
    </div>
    <div class="capability-pills" id="capability-pills"></div>
    <button class="icon-btn project-delete topbar-project-menu" id="open-project-menu" title="聊天管理">•••</button>
    <div class="project-action-menu" id="project-action-menu" hidden>
      <button type="button" id="open-chat-history" data-action-scope="chat"><span>◇</span>历史对话</button>
      <button type="button" id="open-chat-memory" data-action-scope="chat"><span>✦</span>记忆</button>
      <button type="button" id="rename-project-action" data-action-scope="project" hidden><span>✎</span>重命名项目</button>
      <button type="button" id="manage-project-members" data-action-scope="project" hidden><span>♙</span>项目成员</button>
      <button type="button" id="open-project-chat-history" data-action-scope="project" hidden><span>◇</span>项目历史对话</button>
      <button type="button" id="open-project-memory" data-action-scope="project" hidden><span>◇</span>项目记忆</button>
      <button type="button" class="danger" id="delete-project" data-action-scope="project" hidden><span>×</span>删除项目</button>
    </div>
  </header>
</template>
