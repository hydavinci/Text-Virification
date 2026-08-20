export type WorkspaceTool = 'document' | 'issues' | 'search' | 'batch'
export type RailTool = Exclude<WorkspaceTool, 'document'>
export type SidePanelTool = 'issues' | 'batch'
export type InspectorTab = 'details' | 'search'
export type CompactWorkspaceView = WorkspaceTool
