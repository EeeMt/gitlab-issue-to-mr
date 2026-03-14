<template>
  <n-config-provider>
    <n-message-provider>
      <n-layout has-sider position="absolute" style="top: 0; bottom: 0" :native-scrollbar="false">
        <n-layout-sider
          v-if="!isMobile"
          bordered
          collapse-mode="width"
          :collapsed-width="64"
          :width="240"
          :collapsed="collapsed"
          show-trigger
          :native-scrollbar="false"
          content-style="padding: 16px;"
          @collapse="collapsed = true"
          @expand="collapsed = false"
        >
          <div class="logo">
            <n-icon size="24" :component="RocketOutline" />
            <n-text v-if="!collapsed" strong>GitMR Admin</n-text>
          </div>
          <n-menu
            :collapsed="collapsed"
            :collapsed-width="64"
            :options="menuOptions"
            :value="activeKey"
            @update:value="handleMenuUpdate"
          />
        </n-layout-sider>

        <!-- Mobile: collapsible drawer -->
        <n-drawer v-if="isMobile" v-model:show="showDrawer" :width="280" placement="left">
          <n-drawer-content title="GitMR Admin">
            <div class="logo-mobile">
              <n-icon size="24" :component="RocketOutline" />
              <n-text strong>GitMR Admin</n-text>
            </div>
            <n-menu
              :options="menuOptions"
              :value="activeKey"
              @update:value="(key: string) => { handleMenuUpdate(key); showDrawer = false }"
            />
          </n-drawer-content>
        </n-drawer>

        <n-layout :native-scrollbar="false">
          <!-- Mobile top bar (stacks vertically inside content layout) -->
          <div v-if="isMobile" class="mobile-header">
            <n-button quaternary @click="showDrawer = true">
              <template #icon>
                <n-icon :component="MenuOutline" />
              </template>
            </n-button>
            <n-text strong>GitMR Admin</n-text>
          </div>
          <n-layout content-style="padding: 16px;" :native-scrollbar="false">
            <router-view />
          </n-layout>
        </n-layout>
      </n-layout>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { h, ref, computed } from 'vue'
import { NLayout, NLayoutSider, NMenu, NConfigProvider, NMessageProvider, NText, NIcon, NDrawer, NDrawerContent, NButton } from 'naive-ui'
import type { MenuOption } from 'naive-ui'
import { useRouter, useRoute } from 'vue-router'
import { RocketOutline, GridOutline, SpeedometerOutline, SettingsOutline, MenuOutline } from '@vicons/ionicons5'
import { useWindowSize } from '@vueuse/core'

const router = useRouter()
const route = useRoute()
const collapsed = ref(false)
const showDrawer = ref(false)

const { width } = useWindowSize()
const isMobile = computed(() => width.value < 768)

const activeKey = computed(() => route.name as string)

const renderIcon = (icon: any) => () => h(NIcon, null, { default: () => h(icon) })

const menuOptions: MenuOption[] = [
  {
    label: 'Dashboard',
    key: 'Dashboard',
    icon: renderIcon(GridOutline)
  },
  {
    label: 'Monitor',
    key: 'Monitor',
    icon: renderIcon(SpeedometerOutline)
  },
  {
    label: 'Config',
    key: 'Config',
    icon: renderIcon(SettingsOutline)
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
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  font-size: 16px;
  margin-bottom: 16px;
  color: var(--n-text-color-1);
}
.logo .n-icon {
  color: #2080f0;
}
.logo-mobile {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  font-size: 16px;
  margin-bottom: 16px;
  color: var(--n-text-color-1);
  border-bottom: 1px solid var(--n-border-color);
}
.mobile-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--n-border-color);
  background: var(--n-color);
}

a.app-link {
  color: var(--n-text-color-1);
  text-decoration: none;
  border-bottom: 1px solid rgba(32, 128, 240, 0.24);
  transition: color 0.2s ease, border-color 0.2s ease, background-color 0.2s ease;
}

a.app-link:hover {
  color: #2080f0;
  border-bottom-color: rgba(32, 128, 240, 0.55);
}

a.app-link:active {
  color: #1a6fd9;
}

a.app-link:visited {
  color: var(--n-text-color-1);
}

a.app-link:visited:hover {
  color: #2080f0;
}
</style>
