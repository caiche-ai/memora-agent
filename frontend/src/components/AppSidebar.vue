<template>
  <aside class="sidebar" id="sidebar">
    <div class="brand">
      <div class="brand-mark">✦</div>
      <div><strong>Memora</strong><span>智能工作助理</span></div>
      <button class="icon-btn mobile-only" id="close-sidebar" aria-label="关闭导航">×</button>
    </div>

    <div class="sidebar-section-head"><span>项目</span><button class="icon-btn" id="new-project" title="新建项目">＋</button></div>
    <div class="project-list" id="project-list"></div>

    <button class="sidebar-settings" id="open-task-center" :hidden="!isAdmin"><span>◷</span><span>任务中心</span><b id="task-center-badge"></b></button>
    <button class="sidebar-settings" id="open-email-settings" :hidden="!isAdmin"><span>⚙</span><span>邮件设置</span><b id="email-settings-badge">未配置</b></button>
    <button class="sidebar-settings" id="open-user-management" :hidden="!isAdmin"><span>♙</span><span>用户管理</span></button>
    <button class="sidebar-settings" id="open-account-settings" :hidden="!state.authEnabled || !state.currentUser"><span>◎</span><span>账号设置</span></button>
    <div class="sidebar-user" id="sidebar-user" :hidden="!state.authEnabled || !state.currentUser"><span class="sidebar-user-avatar" id="sidebar-user-avatar">{{ avatar }}</span><span><strong id="sidebar-user-name">{{ displayName }}</strong><small id="sidebar-user-role">{{ roleName }}</small></span><button class="icon-btn" id="logout" type="button" title="退出登录">退出</button></div>
    <div class="sidebar-status" id="sidebar-status"><i></i><span>正在检查服务…</span></div>
  </aside>
</template>

<script setup>
import { computed } from "vue";
import { state } from "../stores/appState.js";

const displayName = computed(() => state.currentUser?.displayName || state.currentUser?.username || state.currentUser?.phone || "用户");
const avatar = computed(() => displayName.value.slice(0, 1));
const isAdmin = computed(() => state.currentUser?.role === "admin");
const roleName = computed(() => isAdmin.value ? "管理员" : "成员");
</script>
