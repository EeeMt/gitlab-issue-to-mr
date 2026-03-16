<template>
  <div class="config-page">
    <n-space vertical :size="16">
      <div class="config-page__hero">
        <div>
          <h2 class="config-page__title">{{ t('config.title') }}</h2>
          <p class="config-page__subtitle">
            {{ t('config.subtitle') }}
          </p>
        </div>
        <n-space :size="8" wrap>
          <n-tag v-if="isDirty" size="small" round type="warning">{{ t('config.unsavedChanges') }}</n-tag>
          <n-tag v-else size="small" round type="success">{{ t('config.inSync') }}</n-tag>
          <n-tag size="small" round type="info">{{ t('config.dbOverride') }}</n-tag>
          <n-tag size="small" round>{{ t('config.envFallback') }}</n-tag>
          <n-tag size="small" round>{{ t('config.defaultFallback') }}</n-tag>
        </n-space>
      </div>

      <n-alert type="info" :show-icon="false">
        {{ t('config.secretInfo') }}
      </n-alert>

      <n-grid :cols="isMobile ? 2 : 4" :x-gap="16" :y-gap="16">
        <n-gi v-for="item in summaryItems" :key="item.label">
          <n-card size="small" class="config-summary-card" :bordered="false">
            <div class="config-summary-card__label">{{ item.label }}</div>
            <div class="config-summary-card__value">{{ item.value }}</div>
          </n-card>
        </n-gi>
      </n-grid>

      <n-spin :show="loading">
        <div class="config-form">
          <n-tabs v-model:value="activeConfigTab" type="line" animated class="config-tabs">
            <n-tab-pane name="runtime" :tab="t('config.runtimeTab')">
              <div class="config-layout__main">
                <n-card id="runtime-settings" class="config-form-card" :bordered="false">
                <template #header>
                  <div class="config-card-header">
                    <div>
                      <div class="config-card-header__title">{{ t('config.runtimeSettings') }}</div>
                      <div class="config-card-header__subtitle">{{ t('config.runtimeSettingsSubtitle') }}</div>
                    </div>
                  </div>
                </template>

                <n-form ref="runtimeFormRef" :model="formValue" :rules="runtimeRules" label-placement="top" class="config-section-form">
                <div class="config-form__section">
                  <div class="config-form__section-title">{{ t('config.scheduler') }}</div>
                  <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                    <n-gi>
                      <n-form-item :label="t('config.maxConcurrency')" path="max_concurrency">
                        <n-input-number
                          v-model:value="formValue.max_concurrency"
                          :min="1"
                          :max="20"
                          class="config-form__input"
                        />
                        <template #feedback>
                          {{ t('config.maxConcurrencyHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                      <n-form-item :label="t('config.schedulerInterval')" path="scheduler_interval">
                        <n-input-number
                          v-model:value="formValue.scheduler_interval"
                          :min="1"
                          :max="60"
                          class="config-form__input"
                        />
                        <template #feedback>
                          {{ t('config.schedulerIntervalHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                      <n-form-item :label="t('config.taskTimeout')" path="task_timeout">
                        <n-input-number
                          v-model:value="formValue.task_timeout"
                          :min="60"
                          :max="7200"
                          class="config-form__input"
                        />
                        <template #feedback>
                          {{ t('config.taskTimeoutHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                      <n-form-item :label="t('config.defaultTargetBranch')" path="default_target_branch">
                        <n-input
                          v-model:value="formValue.default_target_branch"
                          placeholder="main"
                          class="config-form__input"
                        />
                        <template #feedback>
                          {{ t('config.defaultTargetBranchHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                  </n-grid>
                </div>

                <div class="config-form__section">
                  <div class="config-form__section-title">{{ t('config.retryAndAlerts') }}</div>
                  <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                    <n-gi>
                      <n-form-item :label="t('config.maxRetries')" path="max_retries">
                        <n-input-number
                          v-model:value="formValue.max_retries"
                          :min="0"
                          :max="10"
                          class="config-form__input"
                        />
                        <template #feedback>
                          {{ t('config.maxRetriesHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                      <n-form-item :label="t('config.retryDelay')" path="retry_delay">
                        <n-input-number
                          v-model:value="formValue.retry_delay"
                          :min="1"
                          :max="3600"
                          class="config-form__input"
                        />
                        <template #feedback>
                          {{ t('config.retryDelayHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                      <n-form-item :label="t('config.alertOnFailure')" path="alert_on_failure">
                        <n-switch v-model:value="formValue.alert_on_failure" />
                        <template #feedback>
                          {{ t('config.alertOnFailureHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                      <n-form-item :label="t('config.alertWebhookStatus')">
                        <n-tag :type="formValue.alert_webhook_url_configured ? 'success' : 'warning'" round>
                          {{ formValue.alert_webhook_url_configured ? t('config.configured') : t('config.missing') }}
                        </n-tag>
                        <template #feedback>
                          {{ t('config.alertWebhookStatusHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi :span="isMobile ? 1 : 2">
                      <n-form-item :label="t('config.alertWebhookUrl')">
                        <n-input
                          v-model:value="formValue.alert_webhook_url_input"
                          type="password"
                          show-password-on="click"
                          :placeholder="
                            formValue.alert_webhook_url_configured
                              ? t('config.configuredEnterNew')
                              : t('config.enterAlertWebhookUrl')
                          "
                          class="config-form__input"
                        />
                        <template #feedback>
                          {{ t('config.alertWebhookHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                  </n-grid>
                </div>

                <div class="config-form__section">
                  <div class="config-form__section-title">{{ t('config.aiProvider') }}</div>
                  <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                    <n-gi>
                      <n-form-item :label="t('config.anthropicBaseUrl')" path="anthropic_base_url">
                        <n-input
                          v-model:value="formValue.anthropic_base_url"
                          placeholder="http://host.docker.internal:11434/v1"
                          class="config-form__input"
                        />
                        <template #feedback>
                          {{ t('config.anthropicBaseUrlHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                      <n-form-item :label="t('config.anthropicModel')" path="anthropic_model">
                        <n-input
                          v-model:value="formValue.anthropic_model"
                          placeholder="claude-sonnet-4-20250514"
                          class="config-form__input"
                        />
                        <template #feedback>
                          {{ t('config.anthropicModelHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                      <n-form-item :label="t('config.claudeMaxTurns')" path="claude_max_turns">
                        <n-input-number
                          v-model:value="formValue.claude_max_turns"
                          :min="1"
                          :max="200"
                          class="config-form__input"
                        />
                        <template #feedback>
                          {{ t('config.claudeMaxTurnsHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                      <n-form-item :label="t('config.anthropicApiKeyStatus')">
                        <n-tag :type="formValue.anthropic_api_key_configured ? 'success' : 'warning'" round>
                          {{ formValue.anthropic_api_key_configured ? t('config.configured') : t('config.missing') }}
                        </n-tag>
                        <template #feedback>
                          {{ t('config.anthropicApiKeyStatusHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi :span="isMobile ? 1 : 2">
                      <n-form-item :label="t('config.anthropicApiKey')">
                        <n-input
                          v-model:value="formValue.anthropic_api_key_input"
                          type="password"
                          show-password-on="click"
                          :placeholder="
                            formValue.anthropic_api_key_configured
                              ? t('config.configuredEnterNew')
                              : t('config.enterAnthropicApiKey')
                          "
                          class="config-form__input"
                        />
                        <template #feedback>
                          {{ t('config.anthropicApiKeyHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                  </n-grid>
                </div>
                <div class="config-card-actions">
                  <n-space :size="12" wrap>
                    <n-button
                      type="primary"
                      @click="handleSaveSection('runtime')"
                      :loading="sectionSaving.runtime"
                      :disabled="isSectionBusy('runtime') || !isSectionDirty('runtime')"
                    >
                      {{ t('config.saveChanges') }}
                    </n-button>
                    <n-button
                      secondary
                      @click="resetSection('runtime')"
                      :disabled="isSectionBusy('runtime') || !isSectionDirty('runtime')"
                    >
                      {{ t('config.revertChanges') }}
                    </n-button>
                    <n-button
                      @click="handleClearSecret('anthropic_api_key')"
                      :disabled="isSectionBusy('runtime') || !formValue.anthropic_api_key_configured"
                    >
                      {{ t('config.clearAnthropicApiKey') }}
                    </n-button>
                    <n-button
                      @click="handleClearSecret('alert_webhook_url')"
                      :disabled="isSectionBusy('runtime') || !formValue.alert_webhook_url_configured"
                    >
                      {{ t('config.clearAlertWebhook') }}
                    </n-button>
                  </n-space>
                </div>
                </n-form>
                </n-card>

                <n-card id="shared-page-settings" class="config-form-card" :bordered="false">
                <template #header>
                  <div class="config-card-header">
                    <div>
                       <div class="config-card-header__title">{{ t('config.sharedPageAccess') }}</div>
                       <div class="config-card-header__subtitle">{{ t('config.sharedPageAccessSubtitle') }}</div>
                    </div>
                  </div>
                </template>

                <n-form :model="formValue" label-placement="top" class="config-section-form">
                <div class="config-form__section">
                   <div class="config-form__section-title">{{ t('config.pagePermissions') }}</div>
                    <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                    <n-gi>
                       <n-form-item :label="t('config.allowMonitor')">
                        <n-switch v-model:value="formValue.allow_monitor_for_users" />
                        <template #feedback>
                           {{ t('config.allowMonitorHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                       <n-form-item :label="t('config.allowScheduleOverview')">
                        <n-switch v-model:value="formValue.allow_schedule_overview_for_users" />
                        <template #feedback>
                           {{ t('config.allowScheduleOverviewHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                       <n-form-item :label="t('config.allowAnalytics')">
                        <n-switch v-model:value="formValue.allow_analytics_for_users" />
                        <template #feedback>
                           {{ t('config.allowAnalyticsHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                   </n-grid>
                 </div>
                <div class="config-card-actions">
                  <n-space :size="12" wrap>
                    <n-button
                      type="primary"
                      @click="handleSaveSection('sharedPages')"
                      :loading="sectionSaving.sharedPages"
                      :disabled="isSectionBusy('sharedPages') || !isSectionDirty('sharedPages')"
                    >
                      {{ t('config.saveChanges') }}
                    </n-button>
                    <n-button
                      secondary
                      @click="resetSection('sharedPages')"
                      :disabled="isSectionBusy('sharedPages') || !isSectionDirty('sharedPages')"
                    >
                      {{ t('config.revertChanges') }}
                    </n-button>
                  </n-space>
                </div>
                </n-form>
                </n-card>
              </div>
            </n-tab-pane>

            <n-tab-pane name="gitlab" :tab="t('config.gitlabTab')">
              <div class="config-layout__main">
                <n-card id="gitlab-settings" class="config-form-card" :bordered="false">
                <template #header>
                  <div class="config-card-header">
                    <div>
                       <div class="config-card-header__title">{{ t('config.gitlabIntegration') }}</div>
                       <div class="config-card-header__subtitle">{{ t('config.gitlabIntegrationSubtitle') }}</div>
                    </div>
                  </div>
                </template>

                <n-form ref="gitlabFormRef" :model="formValue" :rules="gitlabRules" label-placement="top" class="config-section-form">
                 <div class="config-form__section">
                    <div class="config-form__section-title">{{ t('config.gitlabConnection') }}</div>
                  <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                    <n-gi>
                       <n-form-item :label="t('config.gitlabUrl')" path="gitlab_url">
                        <n-input
                          v-model:value="formValue.gitlab_url"
                          placeholder="https://gitlab.example.com"
                          class="config-form__input"
                        />
                        <template #feedback>
                           {{ t('config.gitlabUrlHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                       <n-form-item :label="t('config.gitlabBotTokenStatus')">
                        <n-tag :type="formValue.gitlab_bot_token_configured ? 'success' : 'warning'" round>
                           {{ formValue.gitlab_bot_token_configured ? t('config.configured') : t('config.missing') }}
                        </n-tag>
                        <template #feedback>
                           {{ t('config.gitlabBotTokenStatusHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi :span="isMobile ? 1 : 2">
                       <n-form-item :label="t('config.gitlabBotToken')">
                        <n-input
                          v-model:value="formValue.gitlab_bot_token_input"
                          type="password"
                          show-password-on="click"
                          :placeholder="
                            formValue.gitlab_bot_token_configured
                              ? t('config.configuredEnterNew')
                              : t('config.enterGitlabBotToken')
                          "
                          class="config-form__input"
                        />
                        <template #feedback>
                           {{ t('config.gitlabBotTokenHint') }}
                        </template>
                       </n-form-item>
                     </n-gi>
                   </n-grid>
                 </div>

                  <div class="config-form__section">
                     <div class="config-form__section-title">{{ t('config.webhookAutomation') }}</div>
                    <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                     <n-gi>
                        <n-form-item :label="t('config.gitlabAdminTokenStatus')">
                         <n-tag :type="formValue.gitlab_admin_token_configured ? 'success' : 'warning'" round>
                            {{ formValue.gitlab_admin_token_configured ? t('config.configured') : t('config.missing') }}
                         </n-tag>
                         <template #feedback>
                            {{ t('config.gitlabAdminTokenStatusHint') }}
                         </template>
                       </n-form-item>
                     </n-gi>
                     <n-gi>
                        <n-form-item :label="t('config.gitlabWebhookSecretStatus')">
                         <n-tag :type="formValue.gitlab_webhook_secret_configured ? 'success' : 'warning'" round>
                            {{ formValue.gitlab_webhook_secret_configured ? t('config.configured') : t('config.missing') }}
                         </n-tag>
                         <template #feedback>
                            {{ t('config.gitlabWebhookSecretStatusHint') }}
                         </template>
                       </n-form-item>
                     </n-gi>
                     <n-gi :span="isMobile ? 1 : 2">
                        <n-form-item :label="t('config.gitlabAdminToken')">
                         <n-input
                           v-model:value="formValue.gitlab_admin_token_input"
                           type="password"
                           show-password-on="click"
                           :placeholder="
                             formValue.gitlab_admin_token_configured
                               ? t('config.configuredEnterNew')
                               : t('config.enterGitlabAdminToken')
                           "
                           class="config-form__input"
                         />
                         <template #feedback>
                            {{ t('config.gitlabAdminTokenHint') }}
                         </template>
                       </n-form-item>
                     </n-gi>
                     <n-gi :span="isMobile ? 1 : 2">
                        <n-form-item :label="t('config.gitlabWebhookSecret')">
                         <n-input
                           v-model:value="formValue.gitlab_webhook_secret_input"
                           type="password"
                           show-password-on="click"
                           :placeholder="
                             formValue.gitlab_webhook_secret_configured
                               ? t('config.configuredEnterNew')
                               : t('config.enterGitlabWebhookSecret')
                           "
                           class="config-form__input"
                         />
                         <template #feedback>
                            {{ t('config.gitlabWebhookSecretHint') }}
                         </template>
                       </n-form-item>
                     </n-gi>
                      <n-gi :span="isMobile ? 1 : 2">
                         <n-form-item :label="t('config.webhookOverviewSearch')">
                          <n-input
                            v-model:value="webhookSearch"
                            clearable
                            :placeholder="t('config.webhookOverviewSearchPlaceholder')"
                            class="config-form__input"
                          />
                          <template #feedback>
                             {{ t('config.webhookOverviewHint') }}
                          </template>
                        </n-form-item>
                      </n-gi>
                    </n-grid>
                  </div>

                  <div class="config-form__section">
                    <div class="config-card-header config-card-header--stacked">
                      <div>
                        <div class="config-card-header__title">{{ t('config.webhookOverview') }}</div>
                        <div class="config-card-header__subtitle">{{ t('config.webhookOverviewSubtitle') }}</div>
                      </div>
                      <n-button
                        @click="fetchWebhookStatuses"
                        :loading="webhookStatusLoading"
                        :disabled="isSectionBusy('gitlab')"
                      >
                        {{ t('config.refreshWebhookStatuses') }}
                      </n-button>
                    </div>

                    <n-grid v-if="webhookSummaryItems.length" :cols="isMobile ? 2 : 4" :x-gap="16" :y-gap="16" class="config-webhook-summary">
                      <n-gi v-for="item in webhookSummaryItems" :key="item.label">
                        <n-card size="small" class="config-summary-card" :bordered="false">
                          <div class="config-summary-card__label">{{ item.label }}</div>
                          <div class="config-summary-card__value">{{ item.value }}</div>
                        </n-card>
                      </n-gi>
                    </n-grid>

                    <div v-if="!isMobile" class="config-table-wrapper">
                      <n-data-table
                        :columns="webhookColumns"
                        :data="filteredWebhookStatuses"
                        :loading="webhookStatusLoading"
                        :bordered="false"
                        :pagination="{ pageSize: 10 }"
                        :scroll-x="1100"
                        :row-key="(row: GitLabProjectWebhookStatusResult) => row.project_id"
                      />
                    </div>
                    <n-spin v-else :show="webhookStatusLoading">
                      <div v-if="!webhookStatusLoading && filteredWebhookStatuses.length === 0" class="config-webhook-mobile__empty">
                        {{ t('config.noWebhookData') }}
                      </div>
                      <div
                        v-for="row in filteredWebhookStatuses"
                        :key="row.project_id"
                        class="config-webhook-mobile__item"
                      >
                        <div class="config-webhook-mobile__item-top">
                          <div class="config-webhook-project">
                            <div class="config-webhook-project__name">{{ row.project_path_with_namespace || row.project_name || `#${row.project_id}` }}</div>
                            <div class="config-webhook-project__meta">#{{ row.project_id }}</div>
                          </div>
                          <n-button
                            size="small"
                            :type="row.status === 'configured' ? 'default' : 'primary'"
                            :secondary="row.status !== 'configured'"
                            :loading="webhookActionProjectId === row.project_id"
                            :disabled="isSectionBusy('gitlab') && webhookActionProjectId !== row.project_id"
                            @click="handleSetupProjectWebhook(row.project_id)"
                          >
                            {{ t('config.setupProjectWebhook') }}
                          </n-button>
                        </div>
                        <div class="config-webhook-mobile__item-tags">
                          <n-tag :type="getWebhookStatusTagType(row.status)" size="small" round>{{ getWebhookStatusLabel(row.status) }}</n-tag>
                          <n-tag size="small" round>{{ getWebhookSecretLabel(row.secret_mode) }}</n-tag>
                        </div>
                        <div v-if="row.status_detail || row.hook_url || row.target_webhook_url" class="config-webhook-mobile__item-detail">
                          {{ row.status_detail || row.hook_url || row.target_webhook_url }}
                        </div>
                      </div>
                    </n-spin>
                  </div>
                   <div class="config-card-actions">
                     <n-space :size="12" wrap>
                    <n-button
                      type="primary"
                      @click="handleSaveSection('gitlab')"
                      :loading="sectionSaving.gitlab"
                      :disabled="isSectionBusy('gitlab') || !isSectionDirty('gitlab')"
                    >
                      {{ t('config.saveChanges') }}
                    </n-button>
                    <n-button
                      secondary
                      @click="resetSection('gitlab')"
                      :disabled="isSectionBusy('gitlab') || !isSectionDirty('gitlab')"
                    >
                      {{ t('config.revertChanges') }}
                    </n-button>
                    <n-button
                      @click="handleTestGitLab"
                      :loading="gitlabTesting"
                      :disabled="isSectionBusy('gitlab')"
                    >
                      {{ t('config.testGitlabConnection') }}
                    </n-button>
                     <n-button
                       @click="handleClearSecret('gitlab_bot_token')"
                       :disabled="isSectionBusy('gitlab') || !formValue.gitlab_bot_token_configured"
                     >
                       {{ t('config.clearGitlabBotToken') }}
                     </n-button>
                     <n-button
                       @click="handleClearSecret('gitlab_admin_token')"
                       :disabled="isSectionBusy('gitlab') || !formValue.gitlab_admin_token_configured"
                     >
                       {{ t('config.clearGitlabAdminToken') }}
                     </n-button>
                      <n-button
                        @click="handleClearSecret('gitlab_webhook_secret')"
                        :disabled="isSectionBusy('gitlab') || !formValue.gitlab_webhook_secret_configured"
                      >
                        {{ t('config.clearGitlabWebhookSecret') }}
                      </n-button>
                    </n-space>
                    <n-alert
                      v-if="gitlabTestState"
                      :type="gitlabTestState.type"
                      :show-icon="false"
                      class="config-actions__alert"
                    >
                      {{ gitlabTestState.message }}
                    </n-alert>
                    <n-alert
                      v-if="webhookSetupState"
                      :type="webhookSetupState.type"
                      :show-icon="false"
                      class="config-actions__alert"
                    >
                      {{ webhookSetupState.message }}
                    </n-alert>
                    <n-alert
                      v-if="webhookStatusState"
                      :type="webhookStatusState.type"
                      :show-icon="false"
                      class="config-actions__alert"
                    >
                      {{ webhookStatusState.message }}
                    </n-alert>
                  </div>
                 </n-form>
                </n-card>
              </div>
            </n-tab-pane>

            <n-tab-pane name="auth" :tab="t('config.authenticationTab')">
              <div class="config-layout__main">
                <n-card id="oidc-settings" class="config-form-card" :bordered="false">
                <template #header>
                  <div class="config-card-header">
                    <div>
                       <div class="config-card-header__title">{{ t('config.gitlabOidc') }}</div>
                       <div class="config-card-header__subtitle">{{ t('config.gitlabOidcSubtitle') }}</div>
                    </div>
                  </div>
                </template>

                <n-form ref="oidcFormRef" :model="formValue" :rules="oidcRules" label-placement="top" class="config-section-form">
                <div class="config-form__section">
                   <div class="config-form__section-title">{{ t('config.providerBasics') }}</div>
                  <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                    <n-gi>
                       <n-form-item :label="t('config.enableOidcLogin')" path="oidc_enabled">
                        <n-switch v-model:value="formValue.oidc_enabled" />
                        <template #feedback>
                           {{ t('config.enableOidcLoginHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                       <n-form-item :label="t('config.clientSecretStatus')">
                        <n-tag :type="formValue.oidc_client_secret_configured ? 'success' : 'warning'" round>
                           {{ formValue.oidc_client_secret_configured ? t('config.configured') : t('config.missing') }}
                        </n-tag>
                        <template #feedback>
                           {{ t('config.clientSecretStatusHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                       <n-form-item :label="t('config.issuerUrl')" path="oidc_issuer_url">
                        <n-input
                          v-model:value="formValue.oidc_issuer_url"
                          placeholder="https://gitlab.example.com"
                          class="config-form__input"
                        />
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                       <n-form-item :label="t('config.clientId')" path="oidc_client_id">
                        <n-input v-model:value="formValue.oidc_client_id" class="config-form__input" />
                      </n-form-item>
                    </n-gi>
                    <n-gi :span="isMobile ? 1 : 2">
                       <n-form-item :label="t('config.clientSecret')">
                        <n-input
                          v-model:value="formValue.oidc_client_secret_input"
                          type="password"
                          show-password-on="click"
                          :placeholder="
                            formValue.oidc_client_secret_configured
                               ? t('config.configuredEnterNew')
                               : t('config.enterClientSecret')
                          "
                          class="config-form__input"
                        />
                        <template #feedback>
                           {{ t('config.clientSecretHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi :span="isMobile ? 1 : 2">
                       <n-form-item :label="t('config.redirectUri')" path="oidc_redirect_uri">
                        <n-input
                          v-model:value="formValue.oidc_redirect_uri"
                          placeholder="https://your-domain.example.com/api/auth/callback"
                          class="config-form__input"
                        />
                      </n-form-item>
                    </n-gi>
                  </n-grid>
                </div>
                <n-alert v-if="oidcTestState" :type="oidcTestState.type" :show-icon="false" class="config-actions__alert">
                  {{ oidcTestState.message }}
                </n-alert>
                <div class="config-card-actions">
                  <n-space :size="12" wrap>
                    <n-button
                      type="primary"
                      @click="handleSaveSection('oidc')"
                      :loading="sectionSaving.oidc"
                      :disabled="isSectionBusy('oidc') || !isSectionDirty('oidc')"
                    >
                      {{ t('config.saveChanges') }}
                    </n-button>
                    <n-button
                      secondary
                      @click="resetSection('oidc')"
                      :disabled="isSectionBusy('oidc') || !isSectionDirty('oidc')"
                    >
                      {{ t('config.revertChanges') }}
                    </n-button>
                    <n-button
                      @click="handleTestOidc"
                      :loading="oidcTesting"
                      :disabled="isSectionBusy('oidc')"
                    >
                      {{ t('config.testOidcConnection') }}
                    </n-button>
                     <n-button
                       @click="handleClearSecret('oidc_client_secret')"
                       :disabled="isSectionBusy('oidc') || !formValue.oidc_client_secret_configured"
                    >
                      {{ t('config.clearOidcSecret') }}
                    </n-button>
                  </n-space>
                </div>
                </n-form>
                </n-card>

                <n-card id="session-settings" class="config-form-card" :bordered="false">
                <template #header>
                  <div class="config-card-header">
                    <div>
                       <div class="config-card-header__title">{{ t('config.sessionAccess') }}</div>
                       <div class="config-card-header__subtitle">{{ t('config.sessionAccessSubtitle') }}</div>
                    </div>
                  </div>
                </template>

                <n-form ref="sessionFormRef" :model="formValue" :rules="sessionRules" label-placement="top" class="config-section-form">
                <div class="config-form__section">
                   <div class="config-form__section-title">{{ t('config.sessionPolicy') }}</div>
                  <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                    <n-gi>
                       <n-form-item :label="t('config.sessionCookieName')" path="session_cookie_name">
                        <n-input v-model:value="formValue.session_cookie_name" class="config-form__input" />
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                       <n-form-item :label="t('config.sessionTtl')" path="session_ttl_seconds">
                        <n-input-number
                          v-model:value="formValue.session_ttl_seconds"
                          :min="300"
                          :max="604800"
                          class="config-form__input"
                        />
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                       <n-form-item :label="t('config.cookieSecure')" path="cookie_secure">
                        <n-switch v-model:value="formValue.cookie_secure" />
                        <template #feedback>
                           {{ t('config.cookieSecureHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                       <n-form-item :label="t('config.cookieSameSite')" path="cookie_samesite">
                        <n-select
                          v-model:value="formValue.cookie_samesite"
                          :options="sameSiteOptions"
                          class="config-form__input"
                        />
                      </n-form-item>
                    </n-gi>
                  </n-grid>
                </div>

                <div class="config-form__section">
                   <div class="config-form__section-title">{{ t('config.adminBootstrap') }}</div>
                  <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                    <n-gi>
                       <n-form-item :label="t('config.adminUsernames')">
                        <n-input
                          v-model:value="formValue.auth_admin_usernames"
                           :placeholder="t('config.adminUsernamesPlaceholder')"
                          class="config-form__input"
                        />
                        <template #feedback>
                           {{ t('config.adminUsernamesHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                       <n-form-item :label="t('config.adminGitlabGroups')">
                        <n-input
                          v-model:value="formValue.auth_admin_gitlab_groups"
                           :placeholder="t('config.adminGitlabGroupsPlaceholder')"
                          class="config-form__input"
                        />
                        <template #feedback>
                           {{ t('config.adminGitlabGroupsHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                  </n-grid>
                </div>
                <div class="config-card-actions">
                  <n-space :size="12" wrap>
                    <n-button
                      type="primary"
                      @click="handleSaveSection('session')"
                      :loading="sectionSaving.session"
                      :disabled="isSectionBusy('session') || !isSectionDirty('session')"
                    >
                      {{ t('config.saveChanges') }}
                    </n-button>
                    <n-button
                      secondary
                      @click="resetSection('session')"
                      :disabled="isSectionBusy('session') || !isSectionDirty('session')"
                    >
                      {{ t('config.revertChanges') }}
                    </n-button>
                  </n-space>
                </div>
                </n-form>
                </n-card>

                <OidcDiagnosticsPanel />
              </div>
            </n-tab-pane>

            <n-tab-pane name="maintenance" :tab="t('config.maintenanceTab')">
              <div class="config-layout__main">
                <n-card id="config-actions" class="config-form-card" :bordered="false">
                <template #header>
                  <div class="config-card-header">
                    <div>
                       <div class="config-card-header__title">{{ t('config.actions') }}</div>
                       <div class="config-card-header__subtitle">{{ t('config.actionsSubtitle') }}</div>
                    </div>
                  </div>
                </template>

                  <div class="config-form__section config-page-actions">
                  <n-space :size="12" wrap>
                    <n-button @click="handleReload" :disabled="isBusy">
                      {{ t('common.reload') }}
                    </n-button>
                    <n-button @click="handleReset" :loading="pageActionLoading" :disabled="isBusy" secondary>
                      {{ t('config.resetEnvDefaults') }}
                    </n-button>
                  </n-space>
                  </div>
                </n-card>
              </div>
            </n-tab-pane>
          </n-tabs>
        </div>
      </n-spin>
    </n-space>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NForm,
  NFormItem,
  NGi,
  NGrid,
  NInput,
  NInputNumber,
  NSelect,
  NSpace,
  NSpin,
  NSwitch,
  NTabPane,
  NTag,
  NTabs,
  useMessage,
  type DataTableColumns,
  type FormInst,
  type FormRules
} from 'naive-ui'
import { useWindowSize } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import {
  getConfig,
  listGitLabProjectWebhookStatuses,
  resetConfig,
  resetConfigKey,
  setupGitLabProjectWebhook,
  testGitLabConfig,
  testOidcConfig,
  updateConfig,
  type AuthConfigUpdate,
  type Config,
  type ConfigUpdate,
  type GitLabProjectWebhookSetupResult,
  type GitLabProjectWebhookStatusResult,
  type IntegrationConfigUpdate,
  type RuntimeConfigUpdate
} from '../api'
import OidcDiagnosticsPanel from '../components/config/OidcDiagnosticsPanel.vue'

type ConfigForm = {
  max_concurrency: number
  task_timeout: number
  scheduler_interval: number
  default_target_branch: string
  max_retries: number
  retry_delay: number
  alert_on_failure: boolean
  alert_webhook_url_configured: boolean
  alert_webhook_url_input: string
  anthropic_base_url: string
  anthropic_api_key_configured: boolean
  anthropic_api_key_input: string
  anthropic_model: string
  claude_max_turns: number
  allow_monitor_for_users: boolean
  allow_schedule_overview_for_users: boolean
  allow_analytics_for_users: boolean
  allow_oidc_diagnostics_for_users: boolean
  gitlab_url: string
  gitlab_bot_token_configured: boolean
  gitlab_bot_token_input: string
  gitlab_admin_token_configured: boolean
  gitlab_admin_token_input: string
  gitlab_webhook_secret_configured: boolean
  gitlab_webhook_secret_input: string
  oidc_enabled: boolean
  oidc_issuer_url: string
  oidc_client_id: string
  oidc_redirect_uri: string
  session_cookie_name: string
  session_ttl_seconds: number
  cookie_secure: boolean
  cookie_samesite: string
  auth_admin_usernames: string
  auth_admin_gitlab_groups: string
  oidc_client_secret_configured: boolean
  oidc_client_secret_input: string
}

type TestState = {
  type: 'success' | 'error'
  message: string
}

type ConfigSectionKey = 'runtime' | 'sharedPages' | 'gitlab' | 'oidc' | 'session'
type ConfigTabKey = 'runtime' | 'gitlab' | 'auth' | 'maintenance'

const message = useMessage()
const route = useRoute()
const { t } = useI18n()
const { width } = useWindowSize()
const isMobile = computed(() => width.value < 768)

const loading = ref(false)
const pageActionLoading = ref(false)
const runtimeFormRef = ref<FormInst | null>(null)
const gitlabFormRef = ref<FormInst | null>(null)
const oidcFormRef = ref<FormInst | null>(null)
const sessionFormRef = ref<FormInst | null>(null)
const sectionSaving = reactive<Record<ConfigSectionKey, boolean>>({
  runtime: false,
  sharedPages: false,
  gitlab: false,
  oidc: false,
  session: false
})
const gitlabTesting = ref(false)
const webhookStatusLoading = ref(false)
const webhookActionProjectId = ref<number | null>(null)
const webhookStatuses = ref<GitLabProjectWebhookStatusResult[]>([])
const webhookSearch = ref('')
const oidcTesting = ref(false)
const oidcTestState = ref<TestState | null>(null)
const gitlabTestState = ref<TestState | null>(null)
const webhookSetupState = ref<TestState | null>(null)
const webhookStatusState = ref<TestState | null>(null)
const activeConfigTab = ref<ConfigTabKey>('runtime')
const configTabs: ConfigTabKey[] = ['runtime', 'gitlab', 'auth', 'maintenance']

const sectionKeys: ConfigSectionKey[] = ['runtime', 'sharedPages', 'gitlab', 'oidc', 'session']

const runtimeSectionFields: readonly (keyof ConfigForm)[] = [
  'max_concurrency',
  'task_timeout',
  'scheduler_interval',
  'default_target_branch',
  'max_retries',
  'retry_delay',
  'alert_on_failure',
  'alert_webhook_url_input',
  'anthropic_base_url',
  'anthropic_api_key_input',
  'anthropic_model',
  'claude_max_turns'
]

const sharedPagesSectionFields: readonly (keyof ConfigForm)[] = [
  'allow_monitor_for_users',
  'allow_schedule_overview_for_users',
  'allow_analytics_for_users',
  'allow_oidc_diagnostics_for_users'
]

const gitlabSectionFields: readonly (keyof ConfigForm)[] = [
  'gitlab_url',
  'gitlab_bot_token_input',
  'gitlab_admin_token_input',
  'gitlab_webhook_secret_input'
]

const oidcSectionFields: readonly (keyof ConfigForm)[] = [
  'oidc_enabled',
  'oidc_issuer_url',
  'oidc_client_id',
  'oidc_redirect_uri',
  'oidc_client_secret_input'
]

const sessionSectionFields: readonly (keyof ConfigForm)[] = [
  'session_cookie_name',
  'session_ttl_seconds',
  'cookie_secure',
  'cookie_samesite',
  'auth_admin_usernames',
  'auth_admin_gitlab_groups'
]

const sectionFieldKeys: Record<ConfigSectionKey, readonly (keyof ConfigForm)[]> = {
  runtime: runtimeSectionFields,
  sharedPages: sharedPagesSectionFields,
  gitlab: gitlabSectionFields,
  oidc: oidcSectionFields,
  session: sessionSectionFields
}

const sameSiteOptions = computed(() => [
  { label: 'Lax', value: 'lax' },
  { label: 'Strict', value: 'strict' },
  { label: 'None', value: 'none' }
])

const formValue = ref<ConfigForm>({
  max_concurrency: 3,
  task_timeout: 1800,
  scheduler_interval: 5,
  default_target_branch: 'main',
  max_retries: 0,
  retry_delay: 60,
  alert_on_failure: false,
  alert_webhook_url_configured: false,
  alert_webhook_url_input: '',
  anthropic_base_url: 'http://localhost:11434/v1',
  anthropic_api_key_configured: false,
  anthropic_api_key_input: '',
  anthropic_model: 'claude-sonnet-4-20250514',
  claude_max_turns: 20,
  allow_monitor_for_users: false,
  allow_schedule_overview_for_users: false,
  allow_analytics_for_users: false,
  allow_oidc_diagnostics_for_users: false,
  gitlab_url: '',
  gitlab_bot_token_configured: false,
  gitlab_bot_token_input: '',
  gitlab_admin_token_configured: false,
  gitlab_admin_token_input: '',
  gitlab_webhook_secret_configured: false,
  gitlab_webhook_secret_input: '',
  oidc_enabled: false,
  oidc_issuer_url: '',
  oidc_client_id: '',
  oidc_redirect_uri: '',
  session_cookie_name: 'gimr_session',
  session_ttl_seconds: 28800,
  cookie_secure: true,
  cookie_samesite: 'lax',
  auth_admin_usernames: '',
  auth_admin_gitlab_groups: '',
  oidc_client_secret_configured: false,
  oidc_client_secret_input: ''
})

const lastLoadedValue = ref<ConfigForm>({ ...formValue.value })

const anySectionSaving = computed(() =>
  sectionKeys.some((section) => sectionSaving[section])
)

const isBusy = computed(() =>
  loading.value ||
  pageActionLoading.value ||
  anySectionSaving.value ||
  gitlabTesting.value ||
  webhookStatusLoading.value ||
  webhookActionProjectId.value !== null ||
  oidcTesting.value
)

const filteredWebhookStatuses = computed(() => {
  const keyword = webhookSearch.value.trim().toLowerCase()
  if (!keyword) {
    return webhookStatuses.value
  }

  return webhookStatuses.value.filter((row) => {
    const text = [
      row.project_name,
      row.project_path_with_namespace,
      row.status,
      row.secret_mode,
      row.status_detail || ''
    ]
      .join(' ')
      .toLowerCase()
    return text.includes(keyword)
  })
})

const webhookSummaryItems = computed(() => {
  const rows = webhookStatuses.value
  const configured = rows.filter((row) => row.status === 'configured').length
  const attention = rows.filter((row) => row.status === 'needs_attention').length
  const missingOrError = rows.filter((row) => row.status === 'missing' || row.status === 'error').length

  return [
    { label: t('config.webhookProjectsTotal'), value: String(rows.length) },
    { label: t('config.webhookProjectsConfigured'), value: String(configured) },
    { label: t('config.webhookProjectsAttention'), value: String(attention) },
    { label: t('config.webhookProjectsMissing'), value: String(missingOrError) }
  ]
})

function snapshotSection(section: ConfigSectionKey, value: ConfigForm) {
  const snapshot: Record<string, string | number | boolean> = {}
  for (const key of sectionFieldKeys[section]) {
    snapshot[key] = value[key]
  }
  return snapshot
}

function isSectionDirty(section: ConfigSectionKey) {
  return (
    JSON.stringify(snapshotSection(section, formValue.value)) !==
    JSON.stringify(snapshotSection(section, lastLoadedValue.value))
  )
}

const isDirty = computed(() => sectionKeys.some((section) => isSectionDirty(section)))

const sharedPagesEnabledCount = computed(
  () =>
    [
      formValue.value.allow_monitor_for_users,
      formValue.value.allow_schedule_overview_for_users,
      formValue.value.allow_analytics_for_users
    ].filter(Boolean).length
)

const summaryItems = computed(() => [
  { label: t('config.maxConcurrency'), value: String(formValue.value.max_concurrency) },
  { label: t('config.taskTimeout'), value: `${formValue.value.task_timeout}s` },
  { label: t('config.oidcLogin'), value: formValue.value.oidc_enabled ? t('common.enabled') : t('common.disabled') },
  { label: t('config.sharedPages'), value: String(sharedPagesEnabledCount.value) }
])

const runtimeRules: FormRules = {
  max_concurrency: { required: true, type: 'number', message: t('config.enterMaxConcurrency'), trigger: 'blur' },
  task_timeout: { required: true, type: 'number', message: t('config.enterTaskTimeout'), trigger: 'blur' },
  scheduler_interval: {
    required: true,
    type: 'number',
    message: t('config.enterSchedulerInterval'),
    trigger: 'blur'
  },
  default_target_branch: {
    required: true,
    message: t('config.enterDefaultTargetBranch'),
    trigger: 'blur'
  },
  max_retries: {
    required: true,
    type: 'number',
    message: t('config.enterMaxRetries'),
    trigger: 'blur'
  },
  retry_delay: {
    required: true,
    type: 'number',
    message: t('config.enterRetryDelay'),
    trigger: 'blur'
  },
  anthropic_base_url: {
    required: true,
    message: t('config.enterAnthropicBaseUrl'),
    trigger: 'blur'
  },
  anthropic_model: {
    required: true,
    message: t('config.enterAnthropicModel'),
    trigger: 'blur'
  },
  claude_max_turns: {
    required: true,
    type: 'number',
    message: t('config.enterClaudeMaxTurns'),
    trigger: 'blur'
  }
}

const gitlabRules: FormRules = {
  gitlab_url: {
    required: true,
    message: t('config.enterGitlabUrl'),
    trigger: 'blur'
  }
}

const oidcRules: FormRules = {
  oidc_issuer_url: {
    validator: () =>
      !formValue.value.oidc_enabled || !!formValue.value.oidc_issuer_url.trim() || new Error(t('config.issuerRequired')),
    trigger: ['blur', 'input']
  },
  oidc_client_id: {
    validator: () =>
      !formValue.value.oidc_enabled || !!formValue.value.oidc_client_id.trim() || new Error(t('config.clientIdRequired')),
    trigger: ['blur', 'input']
  },
  oidc_redirect_uri: {
    validator: () =>
      !formValue.value.oidc_enabled || !!formValue.value.oidc_redirect_uri.trim() || new Error(t('config.redirectUriRequired')),
    trigger: ['blur', 'input']
  }
}

const sessionRules: FormRules = {
  session_cookie_name: {
    required: true,
    message: t('config.enterSessionCookieName'),
    trigger: 'blur'
  },
  session_ttl_seconds: {
    required: true,
    type: 'number',
    message: t('config.enterSessionTtl'),
    trigger: 'blur'
  }
}

function copyFields<K extends keyof ConfigForm>(keys: readonly K[], source: ConfigForm, target: ConfigForm) {
  for (const key of keys) {
    target[key] = source[key]
  }
}

function syncForm(config: Config) {
  formValue.value = {
    max_concurrency: config.runtime.max_concurrency,
    task_timeout: config.runtime.task_timeout,
    scheduler_interval: config.runtime.scheduler_interval,
    default_target_branch: config.runtime.default_target_branch,
    max_retries: config.runtime.max_retries,
    retry_delay: config.runtime.retry_delay,
    alert_on_failure: config.runtime.alert_on_failure,
    alert_webhook_url_configured: config.runtime.alert_webhook_url_configured,
    alert_webhook_url_input: '',
    anthropic_base_url: config.runtime.anthropic_base_url,
    anthropic_api_key_configured: config.runtime.anthropic_api_key_configured,
    anthropic_api_key_input: '',
    anthropic_model: config.runtime.anthropic_model,
    claude_max_turns: config.runtime.claude_max_turns,
    allow_monitor_for_users: config.runtime.allow_monitor_for_users,
    allow_schedule_overview_for_users: config.runtime.allow_schedule_overview_for_users,
    allow_analytics_for_users: config.runtime.allow_analytics_for_users,
    allow_oidc_diagnostics_for_users: config.runtime.allow_oidc_diagnostics_for_users,
    gitlab_url: config.integration.gitlab_url,
    gitlab_bot_token_configured: config.integration.gitlab_bot_token_configured,
    gitlab_bot_token_input: '',
    gitlab_admin_token_configured: config.integration.gitlab_admin_token_configured,
    gitlab_admin_token_input: '',
    gitlab_webhook_secret_configured: config.integration.gitlab_webhook_secret_configured,
    gitlab_webhook_secret_input: '',
    oidc_enabled: config.auth.oidc_enabled,
    oidc_issuer_url: config.auth.oidc_issuer_url,
    oidc_client_id: config.auth.oidc_client_id,
    oidc_redirect_uri: config.auth.oidc_redirect_uri,
    session_cookie_name: config.auth.session_cookie_name,
    session_ttl_seconds: config.auth.session_ttl_seconds,
    cookie_secure: config.auth.cookie_secure,
    cookie_samesite: config.auth.cookie_samesite,
    auth_admin_usernames: config.auth.auth_admin_usernames,
    auth_admin_gitlab_groups: config.auth.auth_admin_gitlab_groups,
    oidc_client_secret_configured: config.auth.oidc_client_secret_configured,
    oidc_client_secret_input: ''
  }
  lastLoadedValue.value = { ...formValue.value }
}

function getSectionForm(section: ConfigSectionKey): FormInst | null {
  switch (section) {
    case 'runtime':
      return runtimeFormRef.value
    case 'gitlab':
      return gitlabFormRef.value
    case 'oidc':
      return oidcFormRef.value
    case 'session':
      return sessionFormRef.value
    default:
      return null
  }
}

function isSectionBusy(section: ConfigSectionKey) {
  return (
    loading.value ||
    pageActionLoading.value ||
    anySectionSaving.value ||
    (section === 'gitlab' && gitlabTesting.value) ||
    (section === 'gitlab' && (webhookStatusLoading.value || webhookActionProjectId.value !== null)) ||
    (section === 'oidc' && oidcTesting.value)
  )
}

async function validateSection(section: ConfigSectionKey) {
  const form = getSectionForm(section)
  if (!form) {
    return true
  }

  return await form.validate().then(() => true).catch(() => false)
}

function buildRuntimeSectionUpdate(): RuntimeConfigUpdate {
  const update: RuntimeConfigUpdate = {
    max_concurrency: formValue.value.max_concurrency,
    task_timeout: formValue.value.task_timeout,
    scheduler_interval: formValue.value.scheduler_interval,
    default_target_branch: formValue.value.default_target_branch.trim(),
    max_retries: formValue.value.max_retries,
    retry_delay: formValue.value.retry_delay,
    alert_on_failure: formValue.value.alert_on_failure,
    anthropic_base_url: formValue.value.anthropic_base_url.trim(),
    anthropic_model: formValue.value.anthropic_model.trim(),
    claude_max_turns: formValue.value.claude_max_turns
  }

  if (formValue.value.alert_webhook_url_input.trim()) {
    update.alert_webhook_url = formValue.value.alert_webhook_url_input.trim()
  }

  if (formValue.value.anthropic_api_key_input.trim()) {
    update.anthropic_api_key = formValue.value.anthropic_api_key_input.trim()
  }

  return update
}

function buildSharedPagesSectionUpdate(): RuntimeConfigUpdate {
  return {
    allow_monitor_for_users: formValue.value.allow_monitor_for_users,
    allow_schedule_overview_for_users: formValue.value.allow_schedule_overview_for_users,
    allow_analytics_for_users: formValue.value.allow_analytics_for_users,
    allow_oidc_diagnostics_for_users: formValue.value.allow_oidc_diagnostics_for_users
  }
}

function buildGitlabSectionUpdate(): IntegrationConfigUpdate {
  const update: IntegrationConfigUpdate = {
    gitlab_url: formValue.value.gitlab_url.trim()
  }

  if (formValue.value.gitlab_bot_token_input.trim()) {
    update.gitlab_bot_token = formValue.value.gitlab_bot_token_input.trim()
  }

  if (formValue.value.gitlab_admin_token_input.trim()) {
    update.gitlab_admin_token = formValue.value.gitlab_admin_token_input.trim()
  }

  if (formValue.value.gitlab_webhook_secret_input.trim()) {
    update.gitlab_webhook_secret = formValue.value.gitlab_webhook_secret_input.trim()
  }

  return update
}

function buildOidcSectionUpdate(): AuthConfigUpdate {
  const update: AuthConfigUpdate = {
    oidc_enabled: formValue.value.oidc_enabled,
    oidc_issuer_url: formValue.value.oidc_issuer_url.trim(),
    oidc_client_id: formValue.value.oidc_client_id.trim(),
    oidc_redirect_uri: formValue.value.oidc_redirect_uri.trim()
  }

  if (formValue.value.oidc_client_secret_input.trim()) {
    update.oidc_client_secret = formValue.value.oidc_client_secret_input.trim()
  }

  return update
}

function buildSessionSectionUpdate(): AuthConfigUpdate {
  return {
    session_cookie_name: formValue.value.session_cookie_name.trim(),
    session_ttl_seconds: formValue.value.session_ttl_seconds,
    cookie_secure: formValue.value.cookie_secure,
    cookie_samesite: formValue.value.cookie_samesite,
    auth_admin_usernames: formValue.value.auth_admin_usernames,
    auth_admin_gitlab_groups: formValue.value.auth_admin_gitlab_groups
  }
}

function buildSectionPayload(section: ConfigSectionKey): ConfigUpdate {
  switch (section) {
    case 'runtime':
      return { runtime: buildRuntimeSectionUpdate() }
    case 'sharedPages':
      return { runtime: buildSharedPagesSectionUpdate() }
    case 'gitlab':
      return { integration: buildGitlabSectionUpdate() }
    case 'oidc':
      return { auth: buildOidcSectionUpdate() }
    case 'session':
      return { auth: buildSessionSectionUpdate() }
  }
}

function resetSection(section: ConfigSectionKey) {
  copyFields(sectionFieldKeys[section], lastLoadedValue.value, formValue.value)

  if (section === 'gitlab') {
    gitlabTestState.value = null
    webhookSetupState.value = null
    webhookStatusState.value = null
  }

  if (section === 'oidc') {
    oidcTestState.value = null
  }
}

async function fetchConfig() {
  loading.value = true
  oidcTestState.value = null
  gitlabTestState.value = null
  try {
    syncForm(await getConfig())
    await fetchWebhookStatuses()
  } catch (error) {
    message.error(t('config.failedToFetchConfig'))
  } finally {
    loading.value = false
  }
}

function getWebhookSecretLabel(secretMode: GitLabProjectWebhookStatusResult['secret_mode']) {
  if (secretMode === 'project') {
    return t('config.webhookSecretModeProject')
  }
  if (secretMode === 'global_fallback') {
    return t('config.webhookSecretModeGlobalFallback')
  }
  return t('config.webhookSecretModeNone')
}

function getWebhookStatusLabel(status: GitLabProjectWebhookStatusResult['status']) {
  if (status === 'configured') {
    return t('config.webhookStatusConfigured')
  }
  if (status === 'needs_attention') {
    return t('config.webhookStatusNeedsAttention')
  }
  if (status === 'missing') {
    return t('config.webhookStatusMissing')
  }
  return t('config.webhookStatusError')
}

function getWebhookStatusTagType(status: GitLabProjectWebhookStatusResult['status']): 'success' | 'warning' | 'error' | 'default' {
  if (status === 'configured') {
    return 'success'
  }
  if (status === 'needs_attention') {
    return 'warning'
  }
  if (status === 'missing' || status === 'error') {
    return 'error'
  }
  return 'default'
}

const webhookColumns = computed<DataTableColumns<GitLabProjectWebhookStatusResult>>(() => [
  {
    title: t('config.webhookProjectColumn'),
    key: 'project',
    minWidth: 240,
    render: (row) =>
      h('div', { class: 'config-webhook-project' }, [
        h('div', { class: 'config-webhook-project__name' }, row.project_path_with_namespace || row.project_name || `#${row.project_id}`),
        h('div', { class: 'config-webhook-project__meta' }, `#${row.project_id}`)
      ])
  },
  {
    title: t('config.webhookStatusColumn'),
    key: 'status',
    width: 150,
    render: (row) =>
      h(NTag, { type: getWebhookStatusTagType(row.status), round: true }, { default: () => getWebhookStatusLabel(row.status) })
  },
  {
    title: t('config.webhookSecretModeColumn'),
    key: 'secret_mode',
    width: 170,
    render: (row) => h(NTag, { round: true }, { default: () => getWebhookSecretLabel(row.secret_mode) })
  },
  {
    title: t('config.webhookChecksColumn'),
    key: 'checks',
    minWidth: 220,
    render: (row) =>
      h('div', { class: 'config-webhook-checks' }, [
        h('span', `${t('config.webhookHookIdShort')}: ${row.hook_id ?? '-'}`),
        h('span', `${t('config.webhookNoteEventsShort')}: ${row.note_events === null ? '-' : row.note_events ? t('common.enabled') : t('common.disabled')}`),
        h('span', `${t('config.webhookSslShort')}: ${row.enable_ssl_verification === null ? '-' : row.enable_ssl_verification ? t('common.enabled') : t('common.disabled')}`)
      ])
  },
  {
    title: t('config.webhookStatusDetailColumn'),
    key: 'status_detail',
    minWidth: 220,
    render: (row) => row.status_detail || row.hook_url || row.target_webhook_url
  },
  {
    title: t('config.actions'),
    key: 'actions',
    width: 140,
    fixed: isMobile.value ? undefined : 'right',
    render: (row) =>
      h(
        NButton,
        {
          size: 'small',
          type: row.status === 'configured' ? 'default' : 'primary',
          secondary: row.status !== 'configured',
          loading: webhookActionProjectId.value === row.project_id,
          disabled: isSectionBusy('gitlab') && webhookActionProjectId.value !== row.project_id,
          onClick: () => handleSetupProjectWebhook(row.project_id)
        },
        { default: () => t('config.setupProjectWebhook') }
      )
  }
])

async function fetchWebhookStatuses() {
  try {
    if (!formValue.value.gitlab_url.trim() || !formValue.value.gitlab_admin_token_configured) {
      webhookStatuses.value = []
      return
    }

    webhookStatusLoading.value = true
    webhookStatusState.value = null
    webhookStatuses.value = await listGitLabProjectWebhookStatuses()
  } catch (error: any) {
    webhookStatuses.value = []
    const detail = error?.response?.data?.detail || t('config.projectWebhookStatusFailed')
    webhookStatusState.value = { type: 'error', message: detail }
  } finally {
    webhookStatusLoading.value = false
  }
}

async function handleSaveSection(section: ConfigSectionKey) {
  const valid = await validateSection(section)
  if (!valid) {
    return
  }

  sectionSaving[section] = true
  try {
    syncForm(await updateConfig(buildSectionPayload(section)))
    if (section === 'gitlab') {
      gitlabTestState.value = null
      webhookSetupState.value = null
      webhookStatusState.value = null
      await fetchWebhookStatuses()
    }
    if (section === 'oidc') {
      oidcTestState.value = null
    }
    message.success(t('config.configurationSaved'))
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.failedToSaveConfig'))
  } finally {
    sectionSaving[section] = false
  }
}

async function handleTestGitLab() {
  gitlabTesting.value = true
  try {
    const result = await testGitLabConfig(buildGitlabSectionUpdate())
    gitlabTestState.value = {
      type: 'success',
      message: t('config.gitlabConnectionSucceeded', {
        url: result.gitlab_url,
        username: result.username,
        version: result.server_version || t('common.notAvailable')
      })
    }
    message.success(t('config.gitlabConnectionPassed'))
  } catch (error: any) {
    const detail = error?.response?.data?.detail || t('config.gitlabConnectionFailed')
    gitlabTestState.value = { type: 'error', message: detail }
    message.error(detail)
  } finally {
    gitlabTesting.value = false
  }
}

async function handleTestOidc() {
  oidcTesting.value = true
  try {
    const result = await testOidcConfig(buildOidcSectionUpdate())
    oidcTestState.value = {
      type: 'success',
      message: t('config.oidcDiscoverySucceeded', {
        issuer: result.issuer || formValue.value.oidc_issuer_url,
        scopes: result.required_scopes.join(', ')
      })
    }
    message.success(t('config.oidcConnectionPassed'))
  } catch (error: any) {
    const detail = error?.response?.data?.detail || t('config.oidcConnectionFailed')
    oidcTestState.value = { type: 'error', message: detail }
    message.error(detail)
  } finally {
    oidcTesting.value = false
  }
}

function buildWebhookSetupMessage(result: GitLabProjectWebhookSetupResult): string {
  const projectLabel = result.project_path_with_namespace || result.project_name || `#${result.project_id}`
  if (result.action === 'created') {
    return t('config.projectWebhookCreated', { project: projectLabel, hookId: result.hook_id })
  }
  return t('config.projectWebhookUpdated', { project: projectLabel, hookId: result.hook_id })
}

async function handleSetupProjectWebhook(projectId: number) {
  webhookActionProjectId.value = projectId
  try {
    const result = await setupGitLabProjectWebhook(projectId)
    const successMessage = buildWebhookSetupMessage(result)
    webhookSetupState.value = { type: 'success', message: successMessage }
    await fetchWebhookStatuses()
    message.success(successMessage)
  } catch (error: any) {
    const detail = error?.response?.data?.detail || t('config.projectWebhookSetupFailed')
    webhookSetupState.value = { type: 'error', message: detail }
    message.error(detail)
  } finally {
    webhookActionProjectId.value = null
  }
}

async function handleClearSecret(
  key:
    | 'oidc_client_secret'
    | 'anthropic_api_key'
    | 'alert_webhook_url'
    | 'gitlab_bot_token'
    | 'gitlab_admin_token'
    | 'gitlab_webhook_secret',
) {
  const section: ConfigSectionKey =
    key === 'gitlab_bot_token' || key === 'gitlab_admin_token' || key === 'gitlab_webhook_secret'
      ? 'gitlab'
      : key === 'oidc_client_secret'
        ? 'oidc'
        : 'runtime'

  sectionSaving[section] = true
  try {
    if (key === 'gitlab_bot_token') {
      syncForm(await updateConfig({ integration: { clear_gitlab_bot_token: true } }))
      gitlabTestState.value = null
      message.success(t('config.gitlabBotTokenCleared'))
    } else if (key === 'gitlab_admin_token') {
      syncForm(await updateConfig({ integration: { clear_gitlab_admin_token: true } }))
      webhookSetupState.value = null
      webhookStatusState.value = null
      message.success(t('config.gitlabAdminTokenCleared'))
    } else if (key === 'gitlab_webhook_secret') {
      syncForm(await updateConfig({ integration: { clear_gitlab_webhook_secret: true } }))
      webhookSetupState.value = null
      webhookStatusState.value = null
      message.success(t('config.gitlabWebhookSecretCleared'))
    } else if (key === 'oidc_client_secret') {
      syncForm(await resetConfigKey(key))
      message.success(t('config.oidcSecretCleared'))
    } else if (key === 'anthropic_api_key') {
      syncForm(await updateConfig({ runtime: { clear_anthropic_api_key: true } }))
      message.success(t('config.anthropicApiKeyCleared'))
    } else {
      syncForm(await updateConfig({ runtime: { clear_alert_webhook_url: true } }))
      message.success(t('config.alertWebhookCleared'))
    }
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.failedToClearSecret'))
  } finally {
    sectionSaving[section] = false
  }
}

async function handleReset() {
  pageActionLoading.value = true
  try {
    syncForm(await resetConfig())
    oidcTestState.value = null
    gitlabTestState.value = null
    webhookSetupState.value = null
    webhookStatusState.value = null
    message.success(t('config.resetToDefaults'))
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.failedToResetConfig'))
  } finally {
    pageActionLoading.value = false
  }
}

function handleReload() {
  fetchConfig()
}

onMounted(() => {
  fetchConfig()
})

watch(
  () => route.query.tab,
  (tab) => {
    if (typeof tab === 'string' && configTabs.includes(tab as ConfigTabKey)) {
      activeConfigTab.value = tab as ConfigTabKey
    }
  },
  { immediate: true }
)
</script>

<style scoped>
.config-page {
  max-width: 1240px;
}

.config-page__hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.config-page__title {
  margin: 0;
  font-size: 28px;
  line-height: 1.2;
}

.config-page__subtitle {
  margin: 8px 0 0;
  color: rgba(15, 23, 42, 0.68);
  max-width: 760px;
}

.config-summary-card {
  background: linear-gradient(180deg, rgba(32, 128, 240, 0.06), rgba(32, 128, 240, 0.02));
  border-radius: 12px;
}

.config-summary-card__label {
  font-size: 12px;
  color: rgba(15, 23, 42, 0.6);
  margin-bottom: 8px;
}

.config-summary-card__value {
  font-size: 20px;
  font-weight: 600;
  color: var(--n-text-color-1);
  word-break: break-word;
}

.config-form-card {
  border-radius: 18px;
}

.config-layout__main {
  display: grid;
  gap: 16px;
}

.config-tabs :deep(.n-tabs-nav) {
  margin-bottom: 20px;
}

.config-tabs :deep(.n-tabs-tab) {
  border-radius: 999px;
}

.config-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.config-card-header--stacked {
  margin-bottom: 16px;
}

.config-card-header__title {
  font-size: 18px;
  font-weight: 600;
}

.config-card-header__subtitle {
  font-size: 13px;
  color: rgba(15, 23, 42, 0.58);
  margin-top: 4px;
}

.config-form {
  margin-top: 8px;
}

.config-section-form {
  display: grid;
}

.config-form__section + .config-form__section {
  margin-top: 20px;
}

.config-form__section-title {
  margin-bottom: 12px;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: rgba(15, 23, 42, 0.62);
  text-transform: uppercase;
}

.config-form__input {
  width: 100%;
}

.config-actions__alert {
  margin-top: 16px;
}

.config-webhook-summary {
  margin-bottom: 16px;
}

.config-webhook-project {
  display: grid;
  gap: 4px;
}

.config-webhook-project__name {
  font-weight: 600;
}

.config-webhook-project__meta {
  font-size: 12px;
  color: rgba(15, 23, 42, 0.56);
}

.config-webhook-checks {
  display: grid;
  gap: 4px;
}

.config-card-actions {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid rgba(15, 23, 42, 0.08);
}

.config-card-actions :deep(.n-button),
.config-page-actions :deep(.n-button) {
  border-radius: 999px;
}

@media (max-width: 767px) {
  .config-page__hero,
  .config-card-header {
    flex-direction: column;
    align-items: flex-start;
    width: 100%;
  }

  .config-page__title {
    font-size: 24px;
  }

  .config-page__subtitle {
    max-width: none;
  }

  .config-card-header--stacked :deep(.n-button) {
    width: 100%;
  }

  .config-form-card :deep(.n-card-content) {
    padding-left: 16px;
    padding-right: 16px;
  }
}

.config-webhook-mobile__empty {
  padding: 24px 0;
  text-align: center;
  color: rgba(15, 23, 42, 0.45);
  font-size: 14px;
}

.config-webhook-mobile__item {
  padding: 12px 0;
  border-bottom: 1px solid rgba(15, 23, 42, 0.06);
}

.config-webhook-mobile__item:last-child {
  border-bottom: none;
}

.config-webhook-mobile__item-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 8px;
}

.config-webhook-mobile__item-top :deep(.n-button) {
  flex-shrink: 0;
  border-radius: 999px;
}

.config-webhook-mobile__item-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.config-webhook-mobile__item-detail {
  margin-top: 6px;
  font-size: 12px;
  color: rgba(15, 23, 42, 0.56);
  word-break: break-all;
}
</style>
