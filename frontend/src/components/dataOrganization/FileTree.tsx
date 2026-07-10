import { Box, Typography } from '@mui/material'
import { SimpleTreeView } from '@mui/x-tree-view/SimpleTreeView'
import { TreeItem } from '@mui/x-tree-view/TreeItem'

export type FileNode = {
  name: string
  kind: 'dir' | 'file'
  comment?: string
  children?: FileNode[]
}

// itemId = slash path from the root, stable + unique within one tree.
function renderNodes(nodes: FileNode[], parentId = ''): React.ReactNode {
  return nodes.map((node) => {
    const itemId = parentId ? `${parentId}/${node.name}` : node.name
    return (
      <TreeItem
        key={itemId}
        itemId={itemId}
        label={
          <Box component="span" sx={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
            {node.name}
            {node.kind === 'dir' ? '/' : ''}
            {node.comment && (
              <Typography component="span" color="text.secondary" sx={{ ml: 2, fontFamily: 'monospace' }}>
                # {node.comment}
              </Typography>
            )}
          </Box>
        }
      >
        {node.children ? renderNodes(node.children, itemId) : null}
      </TreeItem>
    )
  })
}

function collectDirIds(nodes: FileNode[], parentId = ''): string[] {
  return nodes.flatMap((node) => {
    const itemId = parentId ? `${parentId}/${node.name}` : node.name
    return node.children ? [itemId, ...collectDirIds(node.children, itemId)] : []
  })
}

export function FileTree({ nodes }: { nodes: FileNode[] }) {
  // Read-only reference tree: expand everything, disable selection.
  return (
    <SimpleTreeView
      defaultExpandedItems={collectDirIds(nodes)}
      disableSelection
      sx={{
        overflowX: 'auto',
        p: 1.5,
        border: 1,
        borderColor: 'divider',
        borderRadius: 1,
        bgcolor: 'action.hover',
        // Vertical guide lines to distinguish nesting levels.
        '& .MuiTreeItem-groupTransition': {
          ml: '10px',
          pl: '14px',
          borderLeft: 1,
          borderColor: 'divider',
        },
        '& .MuiTreeItem-content': { py: 0.25 },
      }}
    >
      {renderNodes(nodes)}
    </SimpleTreeView>
  )
}
