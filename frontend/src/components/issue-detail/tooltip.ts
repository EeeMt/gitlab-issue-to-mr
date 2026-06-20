import type { CSSProperties } from 'vue'
import type { TooltipProps } from 'naive-ui'

export const issueDetailTooltipContentStyle: CSSProperties = {
  maxWidth: '420px',
  color: '#fff',
  fontSize: '12px',
  lineHeight: '1.5',
  overflowWrap: 'anywhere',
  whiteSpace: 'pre-wrap',
}

export const issueDetailTooltipThemeOverrides: NonNullable<TooltipProps['themeOverrides']> = {
  color: '#111827',
  textColor: '#fff',
  borderRadius: '6px',
  padding: '6px 9px',
}
