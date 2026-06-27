import { describe, expect, it } from 'vitest'

import en from './en'
import zhCN from './zh-CN'

describe('task mode copy', () => {
  it('presents execute and plan as implementation and analysis modes', () => {
    expect(zhCN.issue.taskModeExecute).toBe('实施模式')
    expect(zhCN.issue.taskModePlan).toBe('分析模式')
    expect(zhCN.taskView.taskModeExecute).toBe('实施模式')
    expect(zhCN.taskView.taskModePlan).toBe('分析模式')
    expect(zhCN.config.defaultExecuteRunInstruction).toBe('默认实施模式运行指令')
    expect(zhCN.config.defaultPlanRunInstruction).toBe('默认分析模式运行指令')

    expect(en.issue.taskModeExecute).toBe('Implementation')
    expect(en.issue.taskModePlan).toBe('Analysis')
    expect(en.taskView.taskModeExecute).toBe('Implementation')
    expect(en.taskView.taskModePlan).toBe('Analysis')
    expect(en.config.defaultExecuteRunInstruction).toBe('Default Implementation Mode Run Instruction')
    expect(en.config.defaultPlanRunInstruction).toBe('Default Analysis Mode Run Instruction')
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
})
