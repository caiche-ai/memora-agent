<template>
  <div class="memora-app">
    <AuthScreen />

    <div class="app-shell">
      <AppSidebar />

      <main class="main-content">
        <AppHeader />
        <ChatView />
        <ProjectChatView />
      </main>
    </div>

  <div class="project-switch-menu" id="project-switch-menu" role="menu" hidden>
    <div class="project-switch-menu-label">选择项目聊天</div>
    <div class="project-switch-list" id="project-switch-list"></div>
  </div>

  <dialog class="email-dialog file-preview-dialog" id="file-preview-dialog">
    <div class="dialog-card">
      <div class="dialog-head file-preview-head">
        <div><h3 id="file-preview-title">文件预览</h3><input id="file-preview-title-input" type="text" maxlength="180" aria-label="文件名" hidden><p id="file-preview-meta"></p></div>
        <div class="file-preview-actions">
          <button class="icon-btn" id="file-preview-edit" type="button" title="编辑内容" aria-label="编辑内容" hidden>✎</button>
          <button class="icon-btn" id="file-preview-cancel-edit" type="button" title="取消编辑" aria-label="取消编辑" hidden>↶</button>
          <button class="icon-btn file-preview-save" id="file-preview-save" type="button" title="保存内容" aria-label="保存内容" hidden>✓</button>
          <button class="icon-btn file-preview-close" type="button" aria-label="关闭预览">×</button>
        </div>
      </div>
      <div class="file-preview-body" id="file-preview-body"><div class="file-preview-loading">正在加载预览…</div></div>
    </div>
  </dialog>

  <dialog class="email-dialog project-chat-history-dialog" id="project-chat-history-dialog">
    <div class="dialog-card">
      <div class="dialog-head">
        <div><h3>项目历史对话</h3><p id="project-chat-history-meta">搜索并打开项目中的历史对话</p></div>
        <button class="icon-btn project-chat-history-close" type="button" aria-label="关闭全部对话">×</button>
      </div>
      <label class="project-chat-history-search"><span>⌕</span><input id="project-chat-history-search" type="search" placeholder="搜索对话" autocomplete="off"></label>
      <div class="project-chat-history-list" id="project-chat-history-list"></div>
    </div>
  </dialog>

  <dialog class="email-dialog project-chat-history-dialog" id="chat-history-dialog">
    <div class="dialog-card">
      <div class="dialog-head">
        <div><h3>历史对话</h3><p id="chat-history-meta">搜索并打开普通聊天中的历史对话</p></div>
        <button class="icon-btn chat-history-close" type="button" aria-label="关闭历史对话">×</button>
      </div>
      <label class="project-chat-history-search"><span>⌕</span><input id="chat-history-search" type="search" placeholder="搜索对话" autocomplete="off"></label>
      <div class="project-chat-history-list" id="chat-history-list"></div>
    </div>
  </dialog>

  <dialog class="email-dialog task-center-dialog" id="task-center-dialog">
    <div class="dialog-card">
      <div class="dialog-head task-center-head">
        <div><h3>任务中心</h3><p>查看 Agent 运行进度、执行时间线和需要处理的死信任务</p></div>
        <div class="task-center-head-actions"><button class="secondary-button" id="refresh-task-center" type="button">刷新</button><button class="icon-btn task-center-close" type="button" aria-label="关闭任务中心">×</button></div>
      </div>
      <div class="task-center-summary" id="task-center-summary"></div>
      <div class="task-center-toolbar">
        <label>状态<select id="task-status-filter"><option value="all">全部任务</option><option value="active">执行中</option><option value="completed">已完成</option><option value="failed">失败</option><option value="dead_letter">死信</option><option value="cancelled">已取消</option></select></label>
        <span id="task-center-updated"></span>
      </div>
      <div class="task-center-layout">
        <div class="task-center-list" id="task-center-list"></div>
        <div class="task-center-detail" id="task-center-detail"><div class="task-center-empty">选择一个任务查看执行详情</div></div>
      </div>
    </div>
  </dialog>

  <dialog class="email-dialog" id="email-dialog">
    <form method="dialog" class="dialog-card" id="email-form">
      <div class="dialog-head"><div><h3 id="email-dialog-title">发送邮件</h3><p id="email-dialog-description">发送前请确认收件人与正文</p></div><button class="icon-btn dialog-cancel" type="button">×</button></div>
      <label>发件方式<select id="email-provider"></select></label>
      <div class="email-compose-warning" id="email-compose-warning" hidden><span>尚未配置发件邮箱。你可以先填写收件人和邮件内容，发送前再完成配置。</span><button class="text-button" id="configure-email-from-compose" type="button">配置发件邮箱</button></div>
      <label>收件人<input id="email-to" type="text" placeholder="name@example.com" required></label>
      <label>主题<input id="email-subject" type="text" required></label>
      <label>正文<textarea id="email-body" rows="12" required></textarea></label>
      <div class="dialog-actions"><button class="secondary-button dialog-cancel" type="button">取消</button><button class="primary-button" id="confirm-email" type="submit">确认发送</button></div>
    </form>
  </dialog>

  <dialog class="email-dialog project-dialog" id="project-dialog">
    <form method="dialog" class="dialog-card" id="project-form">
      <div class="dialog-head"><div><h3>新建项目</h3><p>把相关聊天、资料、会议、待办和记忆放在一起</p></div><button class="icon-btn project-dialog-cancel" type="button">×</button></div>
      <label>项目名称<input id="project-name" type="text" maxlength="80" placeholder="例如：星河项目" required></label>
      <label>项目说明<textarea id="project-description-input" rows="3" maxlength="300" placeholder="项目目标或背景（选填）"></textarea></label>
      <div class="dialog-actions"><button class="secondary-button project-dialog-cancel" type="button">取消</button><button class="primary-button" type="submit">创建项目</button></div>
    </form>
  </dialog>

  <dialog class="email-dialog add-meeting-dialog" id="add-meeting-dialog">
    <form method="dialog" class="dialog-card" id="add-meeting-form">
      <div class="dialog-head"><div><h3>添加会议</h3><p>填写会议名称并选择会议原文文件。</p></div><button class="icon-btn add-meeting-cancel" type="button">×</button></div>
      <button class="tencent-meeting-entry" id="open-tencent-meeting-import" type="button"><span>腾讯会议</span><strong>从云录制导入逐字稿</strong><b>›</b></button>
      <div class="meeting-import-divider"><span>或上传本地文件</span></div>
      <label>会议名称<input id="add-meeting-name" type="text" maxlength="120" placeholder="例如：项目联调与风险会议" required></label>
      <label>会议文件<input id="add-meeting-file" type="file" accept="text/plain,.txt" required><small class="field-hint">当前支持 TXT 格式，添加后可在会议下预览和生成内容。</small></label>
      <div class="dialog-actions"><button class="secondary-button add-meeting-cancel" type="button">取消</button><button class="primary-button" id="add-meeting-submit" type="submit">添加</button></div>
    </form>
  </dialog>

  <dialog class="email-dialog tencent-meeting-dialog" id="tencent-meeting-dialog">
    <div class="dialog-card">
      <div class="dialog-head"><div><h3>从腾讯会议导入</h3><p>显示最近 30 天的云录制；导入后将作为当前项目的会议原文。</p></div><button class="icon-btn tencent-meeting-close" type="button">×</button></div>
      <div class="tencent-meeting-status" id="tencent-meeting-status"></div>
      <div class="tencent-meeting-records" id="tencent-meeting-records"></div>
      <div class="dialog-actions"><button class="secondary-button" id="refresh-tencent-meetings" type="button">刷新</button><button class="secondary-button tencent-meeting-close" type="button">关闭</button></div>
    </div>
  </dialog>

  <dialog class="email-dialog project-management-dialog" id="project-management-dialog">
    <div class="dialog-card">
      <div class="dialog-head"><div><h3 id="memory-dialog-title">项目记忆</h3><p id="memory-dialog-description">从项目聊天和会议中沉淀的人物、主题、决策与风险。</p></div><button class="icon-btn project-management-close" type="button">×</button></div>
      <section class="project-memory-management">
        <div class="project-memory-head"><div><h4>记忆卡片</h4><p>自动沉淀，也可以手动添加、编辑和置顶。</p></div><div class="memory-head-actions"><b id="project-memory-count">0</b><button class="secondary-button" id="add-memory" type="button">＋ 添加记忆</button></div></div>
        <div class="memory-toolbar">
          <label><span>⌕</span><input id="memory-search" type="search" placeholder="搜索记忆" autocomplete="off"></label>
          <select id="memory-type-filter" aria-label="按类型筛选"><option value="all">全部类型</option><option value="person">人物</option><option value="time">时间</option><option value="location">地点</option><option value="topic">主题</option><option value="preference">偏好</option><option value="fact">事实</option><option value="decision">决策</option><option value="risk">风险</option></select>
        </div>
        <div class="memory-summary" id="memory-summary"></div>
        <div class="memory-grid" id="memory-grid"></div>
      </section>
    </div>
  </dialog>

  <dialog class="email-dialog memory-editor-dialog" id="memory-editor-dialog">
    <form method="dialog" class="dialog-card" id="memory-editor-form">
      <div class="dialog-head"><div><h3 id="memory-editor-title">添加记忆</h3><p id="memory-editor-description">这条记忆会在相关问题中作为长期上下文使用。</p></div><button class="icon-btn memory-editor-cancel" type="button">×</button></div>
      <div class="memory-editor-grid">
        <label>类型<select id="memory-editor-type" required><option value="person">人物</option><option value="time">时间</option><option value="location">地点</option><option value="topic">主题</option><option value="preference">偏好</option><option value="fact" selected>事实</option><option value="decision">决策</option><option value="risk">风险</option></select></label>
        <label>重要度<select id="memory-editor-importance" required><option value="1">1 · 低</option><option value="2">2</option><option value="3" selected>3 · 中</option><option value="4">4</option><option value="5">5 · 高</option></select></label>
        <label>置信度<input id="memory-editor-confidence" type="number" min="0" max="1" step="0.05" value="1"></label>
        <label>敏感级别<select id="memory-editor-sensitivity"><option value="private">普通私有信息</option><option value="sensitive">敏感信息</option></select></label>
      </div>
      <label>主题<input id="memory-editor-subject" type="text" maxlength="80" placeholder="例如：用户偏好、项目规则"></label>
      <label>内容<textarea id="memory-editor-content" rows="6" maxlength="500" placeholder="输入需要长期记住的明确事实" required></textarea></label>
      <div class="memory-editor-grid">
        <label>生效日期<input id="memory-editor-valid-from" type="date"></label>
        <label>失效日期<input id="memory-editor-valid-until" type="date"></label>
      </div>
      <label class="memory-pinned-field"><input id="memory-editor-pinned" type="checkbox"><span>置顶记忆（回答时始终优先加入上下文）</span></label>
      <div class="dialog-actions"><button class="secondary-button memory-editor-cancel" type="button">取消</button><button class="primary-button" id="memory-editor-submit" type="submit">保存</button></div>
    </form>
  </dialog>

  <dialog class="email-dialog project-rename-dialog" id="project-rename-dialog">
    <form method="dialog" class="dialog-card" id="project-rename-form">
      <div class="dialog-head"><div><h3>重命名项目</h3><p>项目中的聊天、资料和会议不会受到影响。</p></div><button class="icon-btn project-rename-cancel" type="button">×</button></div>
      <label>项目名称<input id="project-rename-input" type="text" maxlength="80" required></label>
      <div class="dialog-actions"><button class="secondary-button project-rename-cancel" type="button">取消</button><button class="primary-button" type="submit">保存</button></div>
    </form>
  </dialog>

  <dialog class="email-dialog project-rename-dialog" id="resource-rename-dialog">
    <form method="dialog" class="dialog-card" id="resource-rename-form">
      <div class="dialog-head"><div><h3 id="resource-rename-title">修改名称</h3><p id="resource-rename-description">输入新的名称并保存。</p></div><button class="icon-btn resource-rename-cancel" type="button">×</button></div>
      <label><span id="resource-rename-label">名称</span><input id="resource-rename-input" type="text" maxlength="180" required></label>
      <div class="dialog-actions"><button class="secondary-button resource-rename-cancel" type="button">取消</button><button class="primary-button" id="resource-rename-submit" type="submit">保存</button></div>
    </form>
  </dialog>

  <dialog class="email-dialog settings-dialog" id="email-settings-dialog">
    <form method="dialog" class="dialog-card" id="email-settings-form">
      <div class="dialog-head"><div><h3>邮件设置</h3><p>管理系统邮箱与个人 SMTP 备用邮箱</p></div><button class="icon-btn email-settings-cancel" type="button">×</button></div>
      <div class="provider-card" id="agentmail-provider-card">
        <span class="provider-icon">✦</span>
        <div><strong>AgentMail 系统邮箱</strong><p id="agentmail-provider-description">由管理员统一配置，普通用户无需填写授权码。</p></div>
        <b id="agentmail-provider-status">未配置</b>
      </div>
      <div class="settings-divider"><span>个人 SMTP 邮箱（可选备用）</span></div>
      <div class="settings-grid">
        <label class="settings-wide">SMTP 服务器<input id="smtp-host" type="text" maxlength="255" placeholder="smtp.example.com" required></label>
        <label>端口<input id="smtp-port" type="number" min="1" max="65535" value="587" required></label>
        <label>连接方式<select id="smtp-security"><option value="starttls">STARTTLS</option><option value="ssl">SSL/TLS</option></select></label>
        <label class="settings-wide">用户名<input id="smtp-user" type="text" maxlength="255" autocomplete="username" placeholder="通常是完整邮箱地址"></label>
        <label class="settings-wide">密码或授权码<input id="smtp-password" type="password" maxlength="500" autocomplete="new-password" placeholder="留空表示保持当前授权码"></label>
        <label class="settings-wide">发件人邮箱<input id="smtp-from" type="email" maxlength="320" placeholder="sender@example.com" required></label>
      </div>
      <p class="settings-note" id="email-settings-note">授权码只会加密保存在后端，页面不会读取明文。</p>
      <div class="dialog-actions settings-actions">
        <button class="text-button danger" id="clear-email-settings" type="button">清除配置</button>
        <span class="action-spacer"></span>
        <button class="secondary-button" id="test-email-settings" type="button">测试连接</button>
        <button class="primary-button" id="save-email-settings" type="submit">保存</button>
      </div>
    </form>
  </dialog>

  <dialog class="email-dialog user-management-dialog" id="user-management-dialog">
    <div class="dialog-card">
      <div class="dialog-head"><div><h3>用户与角色</h3><p>管理员可设置用户为管理员或普通成员。</p></div><button class="icon-btn user-management-close" type="button">×</button></div>
      <div class="user-management-list" id="user-management-list"></div>
      <div class="dialog-actions"><button class="secondary-button user-management-close" type="button">关闭</button></div>
    </div>
  </dialog>

  <dialog class="email-dialog project-rename-dialog" id="account-settings-dialog">
    <form method="dialog" class="dialog-card" id="account-settings-form">
      <div class="dialog-head"><div><h3>账号设置</h3><p>设置后可使用账号或手机号加密码登录。</p></div><button class="icon-btn account-settings-close" type="button">×</button></div>
      <label>登录账号<input id="account-username" type="text" autocomplete="username" placeholder="支持任意长度和字符" required></label>
      <label id="account-current-password-field" hidden>当前密码<input id="account-current-password" type="password" autocomplete="current-password" placeholder="修改账号或密码时需要验证"></label>
      <label>新密码<input id="account-new-password" type="password" autocomplete="new-password" placeholder="支持任意长度和字符" required></label>
      <label>确认新密码<input id="account-confirm-password" type="password" autocomplete="new-password" required></label>
      <p class="settings-note">密码只会以不可逆的安全哈希形式保存。修改后，其他设备上的登录会话将退出。</p>
      <div class="settings-divider"><span>备用手机登录（可选）</span></div>
      <label>绑定手机号<input id="account-phone" type="tel" maxlength="32" autocomplete="tel" placeholder="可留空；绑定后支持验证码登录"></label>
      <label>手机验证码<span class="auth-code-row"><input id="account-phone-code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" pattern="[0-9]{6}" placeholder="6 位验证码"><button class="secondary-button" id="send-account-phone-code" type="button">获取验证码</button></span></label>
      <div class="dialog-actions"><button class="secondary-button" id="bind-account-phone" type="button">验证并绑定手机号</button></div>
      <div class="dialog-actions"><button class="secondary-button account-settings-close" type="button">取消</button><button class="primary-button" id="save-account-settings" type="submit">保存</button></div>
    </form>
  </dialog>

  <dialog class="email-dialog user-management-dialog" id="project-members-dialog">
    <div class="dialog-card">
      <div class="dialog-head"><div><h3>项目成员</h3><p>编辑者可修改项目内容，查看者只能读取。</p></div><button class="icon-btn project-members-close" type="button">×</button></div>
      <form class="project-member-add" id="project-member-form">
        <input id="project-member-phone" type="tel" maxlength="32" placeholder="已注册用户的手机号" required>
        <select id="project-member-role"><option value="editor">编辑者</option><option value="viewer">查看者</option></select>
        <button class="primary-button" type="submit">添加</button>
      </form>
      <div class="user-management-list" id="project-members-list"></div>
      <div class="dialog-actions"><button class="secondary-button project-members-close" type="button">关闭</button></div>
    </div>
  </dialog>

    <div class="toast-region" id="toast-region" aria-live="polite"></div>
  </div>
</template>

<script setup>
import AppHeader from "./components/AppHeader.vue";
import AppSidebar from "./components/AppSidebar.vue";
import AuthScreen from "./components/AuthScreen.vue";
import ChatView from "./components/ChatView.vue";
import ProjectChatView from "./components/ProjectChatView.vue";
</script>
