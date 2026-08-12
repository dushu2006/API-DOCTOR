import React, { useMemo, useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  FileCode,
  FileText,
  FileLock,
  Folder,
  FolderOpen,
  Search,
  CheckCircle2,
  RefreshCw
} from 'lucide-react';

function buildFileTreeFromPaths(paths) {
  const root = [];
  for (const path of paths) {
    const parts = path.split('/').filter(Boolean);
    let children = root;
    let parentPath = '';
    parts.forEach((name, index) => {
      const itemPath = parentPath ? `${parentPath}/${name}` : name;
      const isFile = index === parts.length - 1;
      let item = children.find(child => child.name === name);
      if (!item) {
        item = isFile
          ? { name, type: 'file', ext: name.split('.').pop(), path: itemPath }
          : { name, type: 'folder', key: itemPath, children: [] };
        children.push(item);
      }
      if (!isFile) children = item.children;
      parentPath = itemPath;
    });
  }

  const sortTree = items => items
    .sort((a, b) => (a.type === b.type ? a.name.localeCompare(b.name) : a.type === 'folder' ? -1 : 1))
    .map(item => item.type === 'folder' ? { ...item, children: sortTree(item.children) } : item);
  return sortTree(root);
}

export default function Explorer({ 
  selectedFile, 
  setSelectedFile, 
  fileStatuses = {},
  explorerWidth = 240,
  isExplorerOpen = true,
  filesList = [],
  filesTree = null,
  projectName = 'Project Workspace',
  onRefresh,
  isConnected = false
}) {
  const [searchQuery, setSearchQuery] = useState('');
  const [openFolders, setOpenFolders] = useState({});
  const [contextMenu, setContextMenu] = useState(null);

  const fileTree = useMemo(() => {
    if (filesTree && filesTree.length > 0) {
      return filesTree;
    }
    const combinedPaths = Array.from(new Set([
      ...filesList,
      ...Object.keys(fileStatuses || {}),
      ...(selectedFile ? [selectedFile] : [])
    ]));
    return buildFileTreeFromPaths(combinedPaths);
  }, [filesTree, filesList, fileStatuses, selectedFile]);

  if (!isExplorerOpen) return null;

  const toggleFolder = (folderKey) => {
    setOpenFolders(prev => ({
      ...prev,
      [folderKey]: prev[folderKey] === undefined ? false : !prev[folderKey]
    }));
  };

  const isFolderOpen = (key) => {
    if (openFolders[key] !== undefined) return openFolders[key];
    // Default top-level folders open
    return !key.includes('/') || key.split('/').length <= 2;
  };

  const getFileIcon = (ext) => {
    switch (ext?.toLowerCase()) {
      case 'py': return <FileCode size={14} style={{ color: '#3572A5' }} />;
      case 'js':
      case 'jsx': return <FileCode size={14} style={{ color: '#F7DF1E' }} />;
      case 'ts':
      case 'tsx': return <FileCode size={14} style={{ color: '#3178C6' }} />;
      case 'go': return <FileCode size={14} style={{ color: '#00ADD8' }} />;
      case 'rs': return <FileCode size={14} style={{ color: '#DEA584' }} />;
      case 'json': return <FileText size={14} style={{ color: '#CBCB41' }} />;
      case 'env': return <FileLock size={14} style={{ color: '#E8A23D' }} />;
      case 'md': return <FileText size={14} style={{ color: '#7C8CF8' }} />;
      default: return <FileText size={14} style={{ color: 'var(--text-muted)' }} />;
    }
  };

  const renderStatusSuffix = (filePath) => {
    const status = fileStatuses[filePath];
    if (!status) return null;

    if (status === 'reading') {
      return (
        <span style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '11px', color: 'var(--color-accent)' }}>
          <span className="agent-dot" />
          <span>reading</span>
        </span>
      );
    }
    if (status === 'modified') {
      return (
        <span style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '11px', color: 'var(--color-warning)' }}>
          <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: 'var(--color-warning)' }} />
          <span>modified</span>
        </span>
      );
    }
    if (status === 'analyzed') {
      return (
        <span style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '11px', color: 'var(--color-success)' }}>
          <CheckCircle2 size={12} />
          <span style={{ color: 'var(--text-muted)' }}>analyzed</span>
        </span>
      );
    }
    return null;
  };

  const handleContextMenu = (e, file) => {
    e.preventDefault();
    setContextMenu({
      x: e.clientX,
      y: e.clientY,
      file
    });
  };

  const matchesSearch = (item) => {
    if (!searchQuery) return true;
    if (item.type === 'file') {
      return (item.path || item.name).toLowerCase().includes(searchQuery.toLowerCase());
    }
    return item.children ? item.children.some(matchesSearch) : false;
  };

  const renderTree = (items, depth = 0) => {
    return items.map((item) => {
      if (!matchesSearch(item)) return null;

      const itemKey = item.key || item.path || item.name;

      if (item.type === 'folder' || item.children) {
        const isOpen = searchQuery ? true : isFolderOpen(itemKey);
        return (
          <div key={itemKey}>
            <div
              onClick={() => toggleFolder(itemKey)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                paddingLeft: `${depth * 14 + 12}px`,
                height: '24px',
                cursor: 'pointer',
                color: 'var(--text-primary)',
                fontSize: '12px'
              }}
              className="hover-bg"
            >
              {isOpen ? <ChevronDown size={14} style={{ color: 'var(--text-muted)' }} /> : <ChevronRight size={14} style={{ color: 'var(--text-muted)' }} />}
              {isOpen ? <FolderOpen size={14} style={{ color: '#7C8CF8' }} /> : <Folder size={14} style={{ color: 'var(--text-muted)' }} />}
              <span>{item.name}</span>
            </div>
            {isOpen && item.children && renderTree(item.children, depth + 1)}
          </div>
        );
      } else {
        const filePath = item.path || item.name;
        const isSelected = selectedFile === filePath;
        const ext = item.ext || (filePath.includes('.') ? filePath.split('.').pop() : '');
        return (
          <div
            key={filePath}
            onClick={() => setSelectedFile(filePath)}
            onContextMenu={(e) => handleContextMenu(e, item)}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              paddingLeft: `${depth * 14 + 12}px`,
              paddingRight: '12px',
              height: '26px',
              cursor: 'pointer',
              backgroundColor: isSelected ? 'var(--surface-2)' : 'transparent',
              borderLeft: isSelected ? '2px solid var(--color-accent)' : '2px solid transparent',
              color: isSelected ? 'var(--text-primary)' : 'var(--text-muted)',
              fontSize: '12px',
              fontFamily: 'var(--font-mono)'
            }}
            className="hover-bg"
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {getFileIcon(ext)}
              <span>{item.name}</span>
            </div>
            {renderStatusSuffix(filePath)}
          </div>
        );
      }
    });
  };

  return (
    <div 
      onClick={() => setContextMenu(null)}
      style={{
        width: `${explorerWidth}px`,
        height: '100%',
        backgroundColor: 'var(--surface-1)',
        borderRight: '1px solid var(--border-color)',
        display: 'flex',
        flexDirection: 'column',
        userSelect: 'none',
        position: 'relative'
      }}
    >
      {/* Header */}
      <div style={{
        height: '35px',
        padding: '0 12px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        borderBottom: '1px solid var(--border-color)'
      }}>
        <span style={{ 
          fontSize: '11px', 
          fontWeight: 700, 
          letterSpacing: '0.08em', 
          color: 'var(--text-muted)',
          fontFamily: 'var(--font-heading)',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap'
        }}>
          {projectName.toUpperCase()}
        </span>
        {onRefresh && (
          <button 
            onClick={onRefresh}
            title="Refresh repository files"
            style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', display: 'flex', alignItems: 'center' }}
          >
            <RefreshCw size={12} />
          </button>
        )}
      </div>

      {/* Search Input */}
      <div style={{ padding: '6px 8px', borderBottom: '1px solid var(--border-color)' }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          backgroundColor: 'var(--surface-2)',
          border: '1px solid var(--border-color)',
          borderRadius: '4px',
          padding: '4px 8px'
        }}>
          <Search size={13} style={{ color: 'var(--text-muted)' }} />
          <input 
            type="text"
            placeholder="Search repository files..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-primary)',
              fontSize: '11px',
              outline: 'none',
              width: '100%',
              fontFamily: 'var(--font-mono)'
            }}
          />
        </div>
      </div>

      {/* Tree Content */}
      <div style={{ flex: 1, overflowY: 'auto', paddingTop: '4px' }}>
        {fileTree.length > 0 ? (
          renderTree(fileTree)
        ) : (
          <div style={{ padding: '20px 12px', fontSize: '11px', color: 'var(--text-muted)', textAlign: 'center', lineHeight: 1.5 }}>
            {isConnected ? 'No repository files loaded yet.' : 'Connect a GitHub repository'}
          </div>
        )}
      </div>

      {/* Right Click Context Menu */}
      {contextMenu && (
        <div style={{
          position: 'fixed',
          top: contextMenu.y,
          left: contextMenu.x,
          backgroundColor: 'var(--surface-2)',
          border: '1px solid var(--border-color)',
          borderRadius: '6px',
          boxShadow: '0 8px 20px rgba(0,0,0,0.5)',
          padding: '4px 0',
          zIndex: 200,
          width: '150px',
          fontSize: '12px'
        }}>
          <div style={{ padding: '6px 12px', cursor: 'pointer' }} onClick={() => setSelectedFile(contextMenu.file.path || contextMenu.file.name)}>Open</div>
          <div
            style={{ padding: '6px 12px', cursor: 'pointer' }}
            onClick={() => navigator.clipboard.writeText(contextMenu.file.path || contextMenu.file.name)}
          >
            Copy Path
          </div>
        </div>
      )}
    </div>
  );
}
