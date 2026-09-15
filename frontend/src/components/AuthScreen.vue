<template>
  <section class="auth-screen" id="auth-screen" aria-labelledby="auth-title" :hidden="Boolean(state.currentUser)">
    <form class="auth-card" id="auth-form">
      <div class="auth-brand"><div class="brand-mark">✦</div><strong>Memora</strong></div>
      <h1 id="auth-title">登录 Memora</h1>
      <p>注册账号后即可使用账号密码登录，手机号为可选的备用登录方式。</p>
      <div class="auth-tabs" role="tablist" aria-label="登录方式">
        <button class="active" id="auth-mode-password" type="button" role="tab" aria-selected="true" data-auth-mode="password">账号登录</button>
        <button id="auth-mode-sms" type="button" role="tab" aria-selected="false" data-auth-mode="sms">手机登录</button>
        <button id="auth-mode-register" type="button" role="tab" aria-selected="false" data-auth-mode="register">注册账号</button>
      </div>
      <div id="auth-password-fields">
        <label>账号或手机号<input id="auth-account" type="text" autocomplete="username" placeholder="请输入账号或手机号" required></label>
        <label>密码<input id="auth-password" type="password" autocomplete="current-password" placeholder="请输入密码" required></label>
      </div>
      <div id="auth-sms-fields" hidden>
        <label>手机号码<input id="auth-phone" type="tel" autocomplete="tel" maxlength="32" placeholder="请输入已绑定的手机号码"></label>
        <label>验证码<span class="auth-code-row"><input id="auth-code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" pattern="[0-9]{6}" placeholder="6 位验证码"><button class="secondary-button" id="send-auth-code" type="button">获取验证码</button></span></label>
      </div>
      <div id="auth-register-fields" hidden>
        <label>登录账号<input id="register-username" type="text" autocomplete="username" placeholder="支持中文、空格和特殊符号"></label>
        <label>密码<input id="register-password" type="password" autocomplete="new-password" placeholder="支持任意长度和字符"></label>
        <label>确认密码<input id="register-confirm-password" type="password" autocomplete="new-password"></label>
        <label>手机号（可选）<input id="register-phone" type="tel" autocomplete="tel" maxlength="32" placeholder="不填写也可以注册"></label>
        <label>手机验证码（填写手机号时必填）<span class="auth-code-row"><input id="register-code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" pattern="[0-9]{6}" placeholder="6 位验证码"><button class="secondary-button" id="send-register-code" type="button">获取验证码</button></span></label>
      </div>
      <p class="auth-hint" id="auth-hint"></p>
      <button class="primary-button auth-submit" id="auth-submit" type="submit">登录</button>
    </form>
  </section>
</template>

<script setup>
import { state } from "../stores/appState.js";
</script>
