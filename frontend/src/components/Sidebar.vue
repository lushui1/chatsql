<template>
  <aside class="sidebar">
    <div class="sidebar-logo">
      <span class="logo-icon">🔍</span>
      <span class="logo-text">ChatSQL</span>
    </div>
    <nav class="sidebar-nav">
      <button
        v-for="item in navItems"
        :key="item.id"
        :class="['nav-item', { active: currentView === item.id }]"
        @click="$emit('navigate', item.id)"
      >
        <span class="nav-icon">{{ item.icon }}</span>
        <span class="nav-label">{{ item.label }}</span>
      </button>
    </nav>
    <div class="sidebar-footer">
      <button class="theme-toggle" @click="$emit('toggle-theme')">
        {{ isDark ? '☀️' : '🌙' }}
      </button>
    </div>
  </aside>
</template>

<script setup lang="ts">
defineProps<{
  currentView: string
  isDark: boolean
}>()

defineEmits<{
  navigate: [view: string]
  'toggle-theme': []
}>()

const navItems = [
  { id: 'chat', icon: '💬', label: '对话' },
  { id: 'dashboard', icon: '📊', label: '仪表盘' },
  { id: 'settings', icon: '⚙️', label: '设置' },
]
</script>

<style scoped>
.sidebar {
  width: 68px;
  background: #1a1a2e;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  transition: width 0.3s;
  overflow: hidden;
}

.sidebar:hover {
  width: 180px;
}

.sidebar-logo {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 20px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.logo-icon {
  font-size: 22px;
  flex-shrink: 0;
}

.logo-text {
  font-size: 16px;
  font-weight: 700;
  color: #fff;
  white-space: nowrap;
  opacity: 0;
  transition: opacity 0.3s;
}

.sidebar:hover .logo-text {
  opacity: 1;
}

.sidebar-nav {
  flex: 1;
  padding: 12px 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: rgba(255, 255, 255, 0.6);
  cursor: pointer;
  transition: all 0.2s;
  font-size: 14px;
  white-space: nowrap;
  text-align: left;
  width: 100%;
}

.nav-item:hover {
  background: rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.9);
}

.nav-item.active {
  background: rgba(59, 130, 246, 0.25);
  color: #60a5fa;
}

.nav-icon {
  font-size: 18px;
  flex-shrink: 0;
  width: 22px;
  text-align: center;
}

.nav-label {
  opacity: 0;
  transition: opacity 0.3s;
}

.sidebar:hover .nav-label {
  opacity: 1;
}

.sidebar-footer {
  padding: 16px 8px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.theme-toggle {
  width: 100%;
  padding: 10px 14px;
  background: transparent;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 18px;
  color: rgba(255, 255, 255, 0.6);
  transition: all 0.2s;
  text-align: left;
  display: flex;
  align-items: center;
  gap: 12px;
}

.theme-toggle:hover {
  background: rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.9);
}
</style>
