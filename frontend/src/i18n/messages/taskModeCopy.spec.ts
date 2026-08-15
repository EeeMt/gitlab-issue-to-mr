import { describe, expect, it } from 'vitest'

import en from './en'
import zhCN from './zh-CN'

describe('task mode copy', () => {
  it('labels the task input as a prompt', () => {
    expect(zhCN.issue.prompt).toBe('提示词')
    expect(en.issue.prompt).toBe('Prompt')
  })

  it('presents all three task modes with mode-first creation copy', () => {
    expect(zhCN.issue.taskModeChoiceTitle).toBe('选择任务模式')
    expect(zhCN.issue.taskModeChoiceHint).toContain('Harness')
    expect(zhCN.issue.taskModeFreeform).toBe('自由模式')
    expect(zhCN.issue.taskModeFreeformDesc).toContain('无代码变更也可完成任务')
    expect(zhCN.issue.taskModeExecute).toBe('实施模式')
    expect(zhCN.issue.taskModePlan).toBe('分析模式')
    expect(zhCN.issue.changeTaskMode).toBe('更改')
    expect(zhCN.taskView.taskModeExecute).toBe('实施模式')
    expect(zhCN.taskView.taskModePlan).toBe('分析模式')
    expect(zhCN.config.runInstructionImplementationTab).toBe('实施模式')
    expect(zhCN.config.runInstructionAnalysisTab).toBe('分析模式')

    expect(en.issue.taskModeChoiceTitle).toBe('Choose a task mode')
    expect(en.issue.taskModeChoiceHint).toContain('Harness')
    expect(en.issue.taskModeFreeform).toBe('Freeform')
    expect(en.issue.taskModeFreeformDesc).toContain('without code changes')
    expect(en.issue.taskModeExecute).toBe('Implementation')
    expect(en.issue.taskModePlan).toBe('Analysis')
    expect(en.issue.changeTaskMode).toBe('Change')
    expect(en.taskView.taskModeExecute).toBe('Implementation')
    expect(en.taskView.taskModePlan).toBe('Analysis')
    expect(en.config.runInstructionImplementationTab).toBe('Implementation')
    expect(en.config.runInstructionAnalysisTab).toBe('Analysis')
  })

  it('describes analysis mode as project-grounded answers without file changes', () => {
    expect(zhCN.issue.taskModePlanDesc).toContain('根据项目实际情况回答问题')
    expect(zhCN.issue.taskModePlanDesc).toContain('不修改任何文件')
    expect(zhCN.issue.taskModeRequiredFeedback).toContain('分析模式只输出回答、分析或方案')

    expect(en.issue.taskModePlanDesc).toContain('answers questions')
    expect(en.issue.taskModePlanDesc).toContain('based on the actual project')
    expect(en.issue.taskModePlanDesc).toContain('no files are modified')
    expect(en.issue.taskModeRequiredFeedback).toContain(
      'Analysis only outputs answers, analysis, or proposals'
    )
  })

  it('labels the harness engine consistently as Harness', () => {
    expect(zhCN.createTask.harness).toBe('Harness')
    expect(en.createTask.harness).toBe('Harness')
    expect(zhCN.taskView.harness).toBe('Harness')
    expect(en.taskView.harness).toBe('Harness')
    expect(zhCN.issue.defaultHarness).toBe('默认 Harness')
    expect(en.issue.defaultHarness).toBe('Default Harness')
    expect(zhCN.taskView.failureEngineError).toBe('Harness 错误')
    expect(en.taskView.failureEngineError).toBe('Harness error')
    expect(zhCN.createTask.harnessClaude).toBe('Claude')
    expect(en.createTask.harnessClaude).toBe('Claude')
    expect(zhCN.createTask.harnessCodex).toBe('Codex')
    expect(en.createTask.harnessCodex).toBe('Codex')
  })
})
