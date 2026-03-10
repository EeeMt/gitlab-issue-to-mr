<template>
  <n-config-provider>
    <n-message-provider>
      <n-layout has-sider position="absolute" style="top: 0; bottom: 0">
        <n-layout-sider
          bordered
          collapse-mode="width"
          :collapsed-width="64"
          :width="240"
          show-trigger
          :native-scrollbar="false"
          content-style="padding: 24px;"
        >
          <div class="logo">
            <n-text strong>GitMR Admin</n-text>
          </div>
          <n-menu
            :collapsed="collapsed"
            :options="menuOptions"
            :value="activeKey"
            @update:value="handleMenuUpdate"
          />
        </n-layout-sider>
        <n-layout content-style="padding: 24px;" :native-scrollbar="false">
          <router-view />
        </n-layout>
      </n-layout>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { h, ref, computed } from 'vue'
import { NLayout, NLayoutSider, NLayoutContent, NMenu, NConfigProvider, NMessageProvider, NText } from 'naive-ui'
import type { MenuOption } from 'naive-ui'
import { useRouter, useRoute } from 'vue-router'

const router = useRouter()
const route = useRoute()
const collapsed = ref(false)

const activeKey = computed(() => route.name as string)

const menuOptions: MenuOption[] = [
  {
    label: 'Dashboard',
    key: 'Dashboard',
    icon: () => h('span', '📋')
  },
  {
    label: 'Monitor',
    key: 'Monitor',
    icon: () => h('span', '📊')
  },
  {
    label: 'Config',
    key: 'Config',
    icon: () => h('span', '⚙️')
  }
]

function handleMenuUpdate(key: string) {
  router.push({ name: key })
}
</script>

<style>
html, body, #app {
  margin: 0;
  padding: 0;
  height: 100%;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
}
.logo {
  padding: 16px;
  font-size: 18px;
  margin-bottom: 16px;
  text-align: center;
}
</style>
