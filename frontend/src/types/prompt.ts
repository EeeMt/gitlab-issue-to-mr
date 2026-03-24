export interface VariableTip {
  name: string
  tip: string
}

export interface VariableEditorState {
  content: string
  variableTips: Record<string, string>  // variableName -> tip
}
