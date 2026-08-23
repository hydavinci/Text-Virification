export type WorkspaceTool = 'document' | 'issues' | 'search' | 'batch' | 'history'
export type RailTool = Exclude<WorkspaceTool, 'document'>
export type SidePanelTool = 'issues' | 'batch' | 'history'
export type InspectorTab = 'details' | 'search'
export type CompactWorkspaceView = WorkspaceTool
